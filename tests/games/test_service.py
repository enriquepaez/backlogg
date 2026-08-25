from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.games import repository as repo
from backlogg.games import service


def _make_raw_igdb() -> dict:
    return {
        "id": 1942,
        "name": "The Witcher 3: Wild Hunt",
        "slug": "the-witcher-3-wild-hunt",
        "summary": "An open world RPG.",
        "cover": {"image_id": "co1wyy"},
        "first_release_date": 1431993600,  # 2015-05-19 UTC
        "rating": 92.5,
        "rating_count": 5432,
        "game_type": 0,
        "genres": [
            {"name": "Role-playing (RPG)", "slug": "role-playing-rpg"},
        ],
        "platforms": [
            {"name": "PC (Microsoft Windows)", "slug": "win"},
        ],
        "involved_companies": [
            {
                "company": {"name": "CD Projekt Red", "slug": "cd-projekt-red"},
                "developer": True,
                "publisher": False,
            }
        ],
    }


def _make_game_dict() -> dict:
    return {
        "title": "The Witcher 3: Wild Hunt",
        "original_title": None,
        "slug": "the-witcher-3-wild-hunt",
        "overview": "An open world RPG.",
        "release_date": date(2015, 5, 19),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": "https://images.igdb.com/igdb/image/upload/t_cover_big/co1wyy.jpg",
        "backdrop_url": None,
        "rating_external": 9.2,
        "rating_count_external": 5432,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Role-playing (RPG)", "slug": "role-playing-rpg"}],
        "platforms": [{"name": "PC (Microsoft Windows)", "slug": "win"}],
        "companies": [{"name": "CD Projekt Red", "slug": "cd-projekt-red", "role": "DEVELOPER"}],
    }


async def test_get_game_found_in_db(db):
    """When game exists in DB, service returns it without calling IGDB."""
    await repo.upsert_game(db, _make_game_dict())

    with patch.object(service._igdb_client, "get_game_by_slug", new_callable=AsyncMock) as mock_get:
        result = await service.get_game(db, "the-witcher-3-wild-hunt")

    assert result.slug == "the-witcher-3-wild-hunt"
    mock_get.assert_not_called()


async def test_get_game_fallback_to_igdb(db):
    """When game is not in DB, service calls IGDB, persists and returns it."""
    raw = _make_raw_igdb()

    with (
        patch.object(
            service._igdb_client,
            "get_game_by_slug",
            new_callable=AsyncMock,
            return_value=raw,
        ),
        patch.object(
            service._igdb_client,
            "game_to_dict",
            return_value=_make_game_dict(),
        ),
    ):
        result = await service.get_game(db, "the-witcher-3-wild-hunt")

    assert result.title == "The Witcher 3: Wild Hunt"
    assert result.slug == "the-witcher-3-wild-hunt"

    # Verify persisted in DB
    persisted = await repo.get_game_by_slug(db, "the-witcher-3-wild-hunt")
    assert persisted is not None


async def test_get_game_not_found_anywhere(db):
    """When IGDB returns None for both slug and search, service raises HTTP 404."""
    with (
        patch.object(
            service._igdb_client, "get_game_by_slug", new_callable=AsyncMock, return_value=None
        ),
        patch.object(service._igdb_client, "search_games", new_callable=AsyncMock, return_value=[]),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_game(db, "this-game-does-not-exist-9999")

    assert exc_info.value.status_code == 404


def _make_disallowed_game_dict(slug: str, game_type: str = "BUNDLE") -> dict:
    data = _make_game_dict()
    data["slug"] = slug
    data["game_type"] = game_type
    return data


# ── Feature 65: game_category_allowlist ────────────────────────────────────


async def test_get_game_discards_disallowed_category(db):
    """An IGDB result whose category is not in the allowlist is not persisted; 404 instead."""
    raw = _make_raw_igdb()
    raw["slug"] = "bundle-game-not-allowed"

    with (
        patch.object(
            service._igdb_client,
            "get_game_by_slug",
            new_callable=AsyncMock,
            return_value=raw,
        ),
        patch.object(
            service._igdb_client,
            "game_to_dict",
            return_value=_make_disallowed_game_dict("bundle-game-not-allowed"),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_game(db, "bundle-game-not-allowed")

    assert exc_info.value.status_code == 404
    persisted = await repo.get_game_by_slug(db, "bundle-game-not-allowed")
    assert persisted is None


@pytest.mark.parametrize(
    "game_type",
    [
        "MAIN_GAME",
        "DLC_ADDON",
        "EXPANSION",
        "STANDALONE_EXPANSION",
        "EPISODE",
        "SEASON",
        "REMAKE",
        "REMASTER",
    ],
)
async def test_get_game_persists_every_allowed_category(db, game_type):
    """None of the 8 allowed categories is a false negative — every one is persisted."""
    raw = _make_raw_igdb()
    slug = f"allowed-game-{game_type.lower()}"
    raw["slug"] = slug
    game_data = _make_game_dict()
    game_data["slug"] = slug
    game_data["game_type"] = game_type

    with (
        patch.object(
            service._igdb_client,
            "get_game_by_slug",
            new_callable=AsyncMock,
            return_value=raw,
        ),
        patch.object(
            service._igdb_client,
            "game_to_dict",
            return_value=game_data,
        ),
    ):
        result = await service.get_game(db, slug)

    assert result.game_type == game_type
    persisted = await repo.get_game_by_slug(db, slug)
    assert persisted is not None


# ── Feature 67: game_developer_publisher_exposure ────────────────────────────


async def test_get_game_includes_companies(db):
    """get_game exposes developer/publisher companies from company_credits."""
    data = _make_game_dict()
    data["slug"] = "companies-in-detail-game"
    data["companies"] = [
        {"name": "CD Projekt Red", "slug": "cd-projekt-red-detail", "role": "DEVELOPER"},
        {"name": "CD Projekt", "slug": "cd-projekt-detail", "role": "PUBLISHER"},
    ]
    await repo.upsert_game(db, data)

    with patch.object(service._igdb_client, "get_game_by_slug", new_callable=AsyncMock) as mock_get:
        result = await service.get_game(db, "companies-in-detail-game")

    mock_get.assert_not_called()
    assert len(result.companies) == 2
    roles = {c.role: c.name for c in result.companies}
    assert roles["DEVELOPER"] == "CD Projekt Red"
    assert roles["PUBLISHER"] == "CD Projekt"


async def test_get_game_companies_empty_when_none(db):
    """get_game returns companies=[] (not null) when the game has no company credits."""
    data = _make_game_dict()
    data["slug"] = "no-companies-detail-game"
    data["companies"] = []
    await repo.upsert_game(db, data)

    result = await service.get_game(db, "no-companies-detail-game")

    assert result.companies == []


async def test_get_game_title_search_fallback(db):
    """When get_game_by_slug returns None, search_games fallback is used."""
    raw = _make_raw_igdb()
    game_dict = _make_game_dict()

    with (
        patch.object(
            service._igdb_client, "get_game_by_slug", new_callable=AsyncMock, return_value=None
        ),
        patch.object(
            service._igdb_client,
            "search_games",
            new_callable=AsyncMock,
            return_value=[raw],
        ),
        patch.object(
            service._igdb_client,
            "game_to_dict",
            return_value=game_dict,
        ),
    ):
        result = await service.get_game(db, "the-witcher-3-wild-hunt-2015")

    assert result.title == "The Witcher 3: Wild Hunt"

    # Verify the game was persisted using the IGDB slug from game_to_dict
    persisted = await repo.get_game_by_slug(db, "the-witcher-3-wild-hunt")
    assert persisted is not None
