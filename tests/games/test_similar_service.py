"""Tests for get_similar_games service function."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.games import repository as repo
from backlogg.games import service
from backlogg.shared.external_ids import upsert_external_id

# Fake IGDB IDs that do NOT correspond to real games
# Use very high numbers to avoid clashing with the real DB
_SOURCE_IGDB_ID_SIM = "9999901"
_SOURCE_IGDB_ID_LOCAL = "9999902"
_SOURCE_IGDB_ID_LIMIT = "9999903"
_SOURCE_IGDB_ID_EMPTY = "9999904"
_REC_IGDB_ID = 9999910


def _make_source_game_dict(slug: str) -> dict:
    return {
        "title": "Fake Source Game",
        "original_title": None,
        "slug": slug,
        "overview": "A test game.",
        "release_date": date(2010, 7, 16),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 8.0,
        "rating_count_external": 1000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


def _make_source_raw_with_similar(similar_games: list[dict]) -> dict:
    return {
        "id": int(_SOURCE_IGDB_ID_SIM),
        "name": "Fake Source Game",
        "slug": "similar-test-source-sim-2010",
        "summary": "A test game.",
        "first_release_date": 1279238400,
        "rating": 80.0,
        "rating_count": 1000,
        "game_type": 0,
        "similar_games": similar_games,
    }


def _make_rec_raw(igdb_id: int = _REC_IGDB_ID, slug: str = "recommended-game-2008") -> dict:
    return {
        "id": igdb_id,
        "name": "Recommended Game",
        "slug": slug,
        "summary": "A recommended game.",
        "cover": {"image_id": "recimg"},
        "first_release_date": 1216339200,  # 2008-07-18
        "rating": 90.0,
        "rating_count": 28000,
        "game_type": 0,
        "genres": [],
        "platforms": [],
        "involved_companies": [],
    }


async def test_get_similar_games_404_for_unknown_slug(db):
    """Returns 404 when the source game does not exist in DB."""
    with pytest.raises(HTTPException) as exc_info:
        await service.get_similar_games(db, "slug-that-does-not-exist-similar-test-xyz")
    assert exc_info.value.status_code == 404


async def test_get_similar_games_empty_when_no_igdb_id(db):
    """Returns empty results when game has no IGDB external ID."""
    await repo.upsert_game(db, _make_source_game_dict("similar-test-no-igdb-id-2010"))
    # No external ID inserted — simulates a locally-only entry

    result = await service.get_similar_games(db, "similar-test-no-igdb-id-2010")

    assert result.results == []


async def test_get_similar_games_empty_when_no_similar_games_field(db):
    """Returns empty results (no error) when similar_games is absent/empty."""
    game = await repo.upsert_game(db, _make_source_game_dict("similar-test-source-empty-2010"))
    await upsert_external_id(db, "GAME", game.id, "IGDB", _SOURCE_IGDB_ID_EMPTY)

    raw_no_similar = _make_source_raw_with_similar([])
    raw_no_similar["slug"] = "similar-test-source-empty-2010"

    with patch.object(
        service._igdb_client,
        "get_game_by_slug",
        new_callable=AsyncMock,
        return_value=raw_no_similar,
    ):
        result = await service.get_similar_games(db, "similar-test-source-empty-2010")

    assert result.results == []


async def test_get_similar_games_missing_similar_games_key(db):
    """Returns empty results (no error) when similar_games key is entirely absent."""
    game = await repo.upsert_game(db, _make_source_game_dict("similar-test-source-nokey-2010"))
    await upsert_external_id(db, "GAME", game.id, "IGDB", "9999905")

    raw = {
        "id": 9999905,
        "name": "Fake Source Game",
        "slug": "similar-test-source-nokey-2010",
    }

    with patch.object(
        service._igdb_client,
        "get_game_by_slug",
        new_callable=AsyncMock,
        return_value=raw,
    ):
        result = await service.get_similar_games(db, "similar-test-source-nokey-2010")

    assert result.results == []


async def test_get_similar_games_persists_and_returns(db):
    """Similar games not in DB are fetched, persisted, and returned."""
    game = await repo.upsert_game(db, _make_source_game_dict("similar-test-source-sim-2010"))
    await upsert_external_id(db, "GAME", game.id, "IGDB", _SOURCE_IGDB_ID_SIM)

    sim_entry = {"id": _REC_IGDB_ID, "name": "Recommended Game", "slug": "recommended-game-2008"}
    source_raw = _make_source_raw_with_similar([sim_entry])
    rec_detail = _make_rec_raw()

    async def fake_get_game_by_slug(slug: str) -> dict | None:
        if slug == "similar-test-source-sim-2010":
            return source_raw
        if slug == "recommended-game-2008":
            return rec_detail
        return None

    with patch.object(
        service._igdb_client,
        "get_game_by_slug",
        side_effect=fake_get_game_by_slug,
    ):
        result = await service.get_similar_games(db, "similar-test-source-sim-2010")

    assert len(result.results) == 1
    item = result.results[0]
    assert item.title == "Recommended Game"
    assert item.slug == "recommended-game-2008"
    assert item.poster_url is not None
    assert item.release_date == date(2008, 7, 18)
    assert item.rating_external == 9.0
    # Feature 69: a freshly-persisted IGDB item has no community rating yet.
    assert item.rating_internal is None

    # Verify it was persisted
    persisted = await repo.get_game_by_slug(db, "recommended-game-2008")
    assert persisted is not None


async def test_get_similar_games_uses_local_if_already_present(db):
    """Items already in DB are used without re-fetching their detail from IGDB."""
    game = await repo.upsert_game(db, _make_source_game_dict("similar-test-source-local-2010"))
    await upsert_external_id(db, "GAME", game.id, "IGDB", _SOURCE_IGDB_ID_LOCAL)

    # Pre-seed the recommended game in DB
    rec_dict = {
        "title": "Recommended Game",
        "original_title": None,
        "slug": "recommended-game-local-2008",
        "overview": "A recommended game already in DB.",
        "release_date": date(2008, 7, 18),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": "https://images.igdb.com/igdb/image/upload/t_cover_big/rec.jpg",
        "backdrop_url": None,
        "rating_external": 9.0,
        "rating_count_external": 28000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }
    await repo.upsert_game(db, rec_dict)

    sim_entry = {
        "id": _REC_IGDB_ID + 1,
        "name": "Recommended Game Local",
        "slug": "recommended-game-local-2008",
    }
    source_raw = _make_source_raw_with_similar([sim_entry])
    source_raw["slug"] = "similar-test-source-local-2010"

    call_slugs: list[str] = []

    async def fake_get_game_by_slug(slug: str) -> dict | None:
        call_slugs.append(slug)
        if slug == "similar-test-source-local-2010":
            return source_raw
        return None  # should never be called for the already-local slug

    with patch.object(
        service._igdb_client,
        "get_game_by_slug",
        side_effect=fake_get_game_by_slug,
    ):
        result = await service.get_similar_games(db, "similar-test-source-local-2010")

    # get_game_by_slug should only have been called once (for the source game),
    # not again for the already-persisted similar game.
    assert call_slugs == ["similar-test-source-local-2010"]
    assert len(result.results) == 1
    assert result.results[0].slug == "recommended-game-local-2008"


# ── Feature 65: game_category_allowlist ────────────────────────────────────

_DISALLOWED_IGDB_ID = "9999906"


async def test_get_similar_games_skips_disallowed_category(db):
    """A similar-games hit whose category is not allowed is not persisted or returned."""
    game = await repo.upsert_game(db, _make_source_game_dict("similar-test-source-bundle-2010"))
    await upsert_external_id(db, "GAME", game.id, "IGDB", _DISALLOWED_IGDB_ID)

    sim_entry = {"id": 9999930, "name": "Bundle Not A Game", "slug": "bundle-not-a-game"}
    source_raw = _make_source_raw_with_similar([sim_entry])
    source_raw["slug"] = "similar-test-source-bundle-2010"

    bundle_detail = {
        "id": 9999930,
        "name": "Bundle Not A Game",
        "slug": "bundle-not-a-game",
        "summary": "",
        "first_release_date": 1577836800,
        "rating": 70.0,
        "rating_count": 100,
        "game_type": 3,  # BUNDLE — excluded from the allowlist
    }

    async def fake_get_game_by_slug(slug: str) -> dict | None:
        if slug == "similar-test-source-bundle-2010":
            return source_raw
        if slug == "bundle-not-a-game":
            return bundle_detail
        return None

    with patch.object(
        service._igdb_client,
        "get_game_by_slug",
        side_effect=fake_get_game_by_slug,
    ):
        result = await service.get_similar_games(db, "similar-test-source-bundle-2010")

    assert result.results == []
    persisted = await repo.get_game_by_slug(db, "bundle-not-a-game")
    assert persisted is None


async def test_get_similar_games_keeps_allowed_and_drops_disallowed(db):
    """Among multiple similar-games hits, only the allowed-category ones are kept."""
    game = await repo.upsert_game(db, _make_source_game_dict("similar-test-source-mixed-2010"))
    await upsert_external_id(db, "GAME", game.id, "IGDB", "9999907")

    sim_entries = [
        {"id": 9999940, "name": "Allowed Rec Game", "slug": "allowed-rec-game"},
        {"id": 9999941, "name": "Disallowed Rec Game", "slug": "disallowed-rec-game"},
    ]
    source_raw = _make_source_raw_with_similar(sim_entries)
    source_raw["slug"] = "similar-test-source-mixed-2010"

    allowed_detail = _make_rec_raw(igdb_id=9999940, slug="allowed-rec-game")
    disallowed_detail = {
        "id": 9999941,
        "name": "Disallowed Rec Game",
        "slug": "disallowed-rec-game",
        "summary": "",
        "first_release_date": 1577836800,
        "rating": 70.0,
        "rating_count": 100,
        "game_type": 11,  # PORT — excluded from the allowlist
    }

    async def fake_get_game_by_slug(slug: str) -> dict | None:
        if slug == "similar-test-source-mixed-2010":
            return source_raw
        if slug == "allowed-rec-game":
            return allowed_detail
        if slug == "disallowed-rec-game":
            return disallowed_detail
        return None

    with patch.object(
        service._igdb_client,
        "get_game_by_slug",
        side_effect=fake_get_game_by_slug,
    ):
        result = await service.get_similar_games(db, "similar-test-source-mixed-2010")

    assert len(result.results) == 1
    assert result.results[0].slug == "allowed-rec-game"
    assert await repo.get_game_by_slug(db, "allowed-rec-game") is not None
    assert await repo.get_game_by_slug(db, "disallowed-rec-game") is None


# ── Feature 66: rating_display_internal_only ────────────────────────────────


async def test_get_similar_games_orders_by_rating_internal_over_external(db):
    """Results are re-ordered by rating_internal desc, not IGDB's own order.

    IGDB's ``similar_games`` field lists the low-rating_internal game first —
    the response must still surface the high-rating_internal game first,
    even though it has a lower rating_external.
    """
    game = await repo.upsert_game(db, _make_source_game_dict("similar-test-source-order-2010"))
    await upsert_external_id(db, "GAME", game.id, "IGDB", "9999908")

    # Pre-seed both candidates locally with an already-computed rating_internal
    # (feature 62) — IGDB detail fetches always report rating_internal=None,
    # so the ranking signal must come from the already-persisted local row.
    low_internal_high_external = {
        "title": "Low Internal High External",
        "original_title": None,
        "slug": "similar-order-low-internal-2008",
        "overview": "",
        "release_date": date(2008, 7, 18),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 9.5,
        "rating_count_external": 5000,
        "rating_internal": 2.0,
        "rating_count_internal": 3,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }
    high_internal_low_external = {
        "title": "High Internal Low External",
        "original_title": None,
        "slug": "similar-order-high-internal-2009",
        "overview": "",
        "release_date": date(2009, 3, 1),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 1.0,
        "rating_count_external": 5000,
        "rating_internal": 4.5,
        "rating_count_internal": 8,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }
    await repo.upsert_game(db, low_internal_high_external)
    await repo.upsert_game(db, high_internal_low_external)

    # IGDB's own similar_games order lists the low-rating_internal game first.
    sim_entries = [
        {
            "id": 9999950,
            "name": "Low Internal High External",
            "slug": "similar-order-low-internal-2008",
        },
        {
            "id": 9999951,
            "name": "High Internal Low External",
            "slug": "similar-order-high-internal-2009",
        },
    ]
    source_raw = _make_source_raw_with_similar(sim_entries)
    source_raw["slug"] = "similar-test-source-order-2010"

    with patch.object(
        service._igdb_client,
        "get_game_by_slug",
        new_callable=AsyncMock,
        return_value=source_raw,
    ):
        result = await service.get_similar_games(db, "similar-test-source-order-2010")

    slugs = [r.slug for r in result.results]
    assert slugs == [
        "similar-order-high-internal-2009",
        "similar-order-low-internal-2008",
    ]
    # Feature 69: rating_internal travels in the response, with the correct
    # value per item (not just used internally to compute the order).
    assert result.results[0].rating_internal == 4.5
    assert result.results[1].rating_internal == 2.0


async def test_get_similar_games_limits_to_10(db):
    """Only up to 10 results are returned even if IGDB returns more."""
    game = await repo.upsert_game(db, _make_source_game_dict("similar-test-source-limit-2010"))
    await upsert_external_id(db, "GAME", game.id, "IGDB", _SOURCE_IGDB_ID_LIMIT)

    sim_entries = [
        {"id": 9999920 + i, "name": f"Limit Test Game {i}", "slug": f"limit-test-game-{i}"}
        for i in range(15)
    ]
    source_raw = _make_source_raw_with_similar(sim_entries)
    source_raw["slug"] = "similar-test-source-limit-2010"

    def make_detail(sim_slug: str) -> dict:
        idx = int(sim_slug.rsplit("-", 1)[-1])
        return {
            "id": 9999920 + idx,
            "name": f"Limit Test Game {idx}",
            "slug": sim_slug,
            "summary": "",
            "first_release_date": 1577836800,
            "rating": 70.0,
            "rating_count": 1000,
            "game_type": 0,
        }

    async def fake_get_game_by_slug(slug: str) -> dict | None:
        if slug == "similar-test-source-limit-2010":
            return source_raw
        return make_detail(slug)

    with patch.object(
        service._igdb_client,
        "get_game_by_slug",
        side_effect=fake_get_game_by_slug,
    ):
        result = await service.get_similar_games(db, "similar-test-source-limit-2010")

    assert len(result.results) == 10
