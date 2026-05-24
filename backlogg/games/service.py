from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.games import repository as repo
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.games.models import Game
from backlogg.shared.external_ids import upsert_external_id

_igdb_client = IGDBClient()


async def get_game(db: AsyncSession, slug: str) -> Game:
    # 1. Look up in local DB
    game = await repo.get_game_by_slug(db, slug)
    if game:
        return game

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

    return game
