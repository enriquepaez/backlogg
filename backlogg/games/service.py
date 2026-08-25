import re

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.games import repository as repo
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.games.constants import ALLOWED_GAME_TYPES
from backlogg.games.schemas import (
    GameGenreOut,
    GameListItemOut,
    GameListOut,
    GameOut,
    GamePlatformOut,
    GameSortEnum,
    SimilarGameListOut,
    SimilarGameOut,
)
from backlogg.library import service as library_service
from backlogg.shared.catalog_filters import CatalogSearchFilters
from backlogg.shared.credits import get_credits_for_item
from backlogg.shared.external_ids import get_external_id, upsert_external_id
from backlogg.shared.rating_sort import rating_desc_sort_key

_igdb_client = IGDBClient()


def _title_from_slug(slug: str) -> str:
    """Convert an internal slug to a search title.

    Strips a trailing 4-digit year (e.g. "doom-1993" -> "doom") and replaces
    hyphens with spaces so the result can be used as a free-text search query.
    """
    return re.sub(r"-\d{4}$", "", slug).replace("-", " ")


async def list_games(
    db: AsyncSession,
    genre: str | None,
    sort: GameSortEnum,
    page: int,
    limit: int,
    filters: CatalogSearchFilters,
) -> GameListOut:
    items, total = await repo.list_games(
        db, genre=genre, sort=sort, page=page, limit=limit, filters=filters
    )
    list_items = [
        GameListItemOut(
            id=g.id,
            title=g.title,
            slug=g.slug,
            poster_url=g.poster_url,
            release_date=g.release_date,
            rating_external=float(g.rating_external) if g.rating_external is not None else None,
            genres=[genre.slug for genre in g.genres],
        )
        for g in items
    ]
    return GameListOut(items=list_items, total=total, page=page, limit=limit)


async def get_game(db: AsyncSession, slug: str, viewer_id: int | None = None) -> GameOut:
    # 1. Look up in local DB
    game = await repo.get_game_by_slug(db, slug)
    if game is None:
        # 2. Fetch from IGDB by slug
        raw = await _igdb_client.get_game_by_slug(slug)
        if raw is None:
            # 2b. Slug mismatch fallback: search by derived title
            title = _title_from_slug(slug)
            results = await _igdb_client.search_games(title, limit=5)
            if results:
                raw = max(results, key=lambda r: r.get("rating_count") or 0)
        if raw is None:
            raise HTTPException(status_code=404, detail="Game not found")

        # 3. Convert and persist — but only if the category is allowed
        # (feature 65: game_category_allowlist). A disallowed category is
        # treated the same as "no external result".
        game_data = _igdb_client.game_to_dict(raw)
        if game_data["game_type"] not in ALLOWED_GAME_TYPES:
            raise HTTPException(status_code=404, detail="Game not found")
        igdb_id = str(raw.get("id", ""))
        game = await repo.upsert_game(db, game_data)

        # 4. Persist the IGDB external ID
        if igdb_id:
            await upsert_external_id(db, "GAME", game.id, "IGDB", igdb_id)
        await db.commit()

    credits = await get_credits_for_item(db, "GAME", game.id)
    viewer_status = await library_service.get_viewer_status(db, "GAME", game.id, viewer_id)
    return GameOut(
        id=game.id,
        title=game.title,
        original_title=game.original_title,
        slug=game.slug,
        overview=game.overview,
        release_date=game.release_date,
        game_type=game.game_type,
        original_language=game.original_language,
        poster_url=game.poster_url,
        backdrop_url=game.backdrop_url,
        rating_external=float(game.rating_external) if game.rating_external is not None else None,
        rating_count_external=game.rating_count_external,
        rating_internal=(float(game.rating_internal) if game.rating_internal is not None else None),
        rating_count_internal=game.rating_count_internal,
        genres=[GameGenreOut(id=g.id, name=g.name, slug=g.slug) for g in game.genres],
        platforms=[GamePlatformOut(id=p.id, name=p.name, slug=p.slug) for p in game.platforms],
        credits=credits,
        viewer_status=viewer_status,
    )


async def get_similar_games(db: AsyncSession, slug: str) -> SimilarGameListOut:
    # 1. Look up the source game — 404 if it doesn't exist
    game = await repo.get_game_by_slug(db, slug)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")

    # 2. Confirm the source game has an IGDB ID (needed to trust similar_games)
    ext_id = await get_external_id(db, "GAME", game.id, "IGDB")
    if ext_id is None:
        # Game exists locally but has no IGDB ID — return empty results
        return SimilarGameListOut(results=[])

    # 3. Re-fetch the source game from IGDB by slug to get similar_games.*
    # (IGDB relations, not a local genre-overlap heuristic)
    raw = await _igdb_client.get_game_by_slug(game.slug)
    if raw is None:
        return SimilarGameListOut(results=[])

    similar_raw = raw.get("similar_games") or []

    # 4. Persist any new games and collect up to 10 results. IGDB's
    # similar_games order reflects its own curated relations, not rating —
    # results are re-sorted below by rating_internal desc / rating_external
    # desc tie-break (feature 66) so the community's own rating decides what
    # the user sees first, not IGDB's ordering or rating_external.
    results: list[tuple[float | None, float | None, SimilarGameOut]] = []
    for sim in similar_raw[:10]:
        if not isinstance(sim, dict):
            continue

        sim_slug = sim.get("slug")
        if not sim_slug:
            continue

        # Try local DB first
        sim_game = await repo.get_game_by_slug(db, sim_slug)
        if sim_game is None:
            # Fetch full detail and persist
            detail = await _igdb_client.get_game_by_slug(sim_slug)
            if detail is None:
                continue
            game_data = _igdb_client.game_to_dict(detail)
            if game_data["game_type"] not in ALLOWED_GAME_TYPES:
                # Disallowed category (feature 65) — skip, don't persist or
                # include it among the recommendations.
                continue
            sim_game = await repo.upsert_game(db, game_data)
            sim_igdb_id = str(detail.get("id", ""))
            if sim_igdb_id:
                await upsert_external_id(db, "GAME", sim_game.id, "IGDB", sim_igdb_id)
            await db.commit()

        rating_internal = (
            float(sim_game.rating_internal) if sim_game.rating_internal is not None else None
        )
        rating_external = (
            float(sim_game.rating_external) if sim_game.rating_external is not None else None
        )
        results.append(
            (
                rating_internal,
                rating_external,
                SimilarGameOut(
                    title=sim_game.title,
                    slug=sim_game.slug,
                    poster_url=sim_game.poster_url,
                    release_date=sim_game.release_date,
                    rating_external=rating_external,
                ),
            )
        )

    ordered = sorted(results, key=lambda r: rating_desc_sort_key(r[0], r[1]))
    return SimilarGameListOut(results=[out for _, _, out in ordered])
