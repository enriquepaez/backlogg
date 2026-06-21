from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.games import repository as repo
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.games.schemas import (
    GameGenreOut,
    GameListItemOut,
    GameListOut,
    GameOut,
    GamePlatformOut,
    GameSortEnum,
)
from backlogg.shared.credits import get_credits_for_item
from backlogg.shared.external_ids import upsert_external_id

_igdb_client = IGDBClient()


async def list_games(
    db: AsyncSession,
    genre: str | None,
    sort: GameSortEnum,
    page: int,
    limit: int,
) -> GameListOut:
    items, total = await repo.list_games(db, genre=genre, sort=sort, page=page, limit=limit)
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


async def get_game(db: AsyncSession, slug: str) -> GameOut:
    # 1. Look up in local DB
    game = await repo.get_game_by_slug(db, slug)
    if game is None:
        # 2. Fetch from IGDB by slug
        raw = await _igdb_client.get_game_by_slug(slug)
        if raw is None:
            raise HTTPException(status_code=404, detail="Game not found")

        # 3. Convert and persist
        game_data = _igdb_client.game_to_dict(raw)
        igdb_id = str(raw.get("id", ""))
        game = await repo.upsert_game(db, game_data)

        # 4. Persist the IGDB external ID
        if igdb_id:
            await upsert_external_id(db, "GAME", game.id, "IGDB", igdb_id)
        await db.commit()

    credits = await get_credits_for_item(db, "GAME", game.id)
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
        genres=[GameGenreOut(id=g.id, name=g.name, slug=g.slug) for g in game.genres],
        platforms=[GamePlatformOut(id=p.id, name=p.name, slug=p.slug) for p in game.platforms],
        credits=credits,
    )
