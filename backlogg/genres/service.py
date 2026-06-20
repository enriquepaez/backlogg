from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.genres import repository as repo
from backlogg.genres.schemas import GenreListOut, GenreWithCountOut


async def list_genres(
    db: AsyncSession,
    item_type: str | None,
) -> GenreListOut:
    genres: list[GenreWithCountOut] = await repo.list_genres(db, item_type=item_type)
    return GenreListOut(genres=genres)
