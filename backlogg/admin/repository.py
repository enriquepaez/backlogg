"""Admin repository — DB queries for admin stats.

Only this file imports and uses SQLAlchemy for the admin domain.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books.models import Book
from backlogg.games.models import Game
from backlogg.movies.models import Movie
from backlogg.series.models import Series


async def get_stats(db: AsyncSession) -> dict:
    """Execute COUNT/MAX queries for all 4 content types.

    Returns a dict with keys ``movies``, ``series``, ``books``, ``games``.
    Each value is a dict with ``count`` (int) and ``last_synced_at``
    (datetime | None).
    """

    async def _query(model):  # type: ignore[no-untyped-def]
        result = await db.execute(select(func.count(), func.max(model.last_synced_at)))
        row = result.one()
        return {"count": row[0], "last_synced_at": row[1]}

    return {
        "movies": await _query(Movie),
        "series": await _query(Series),
        "books": await _query(Book),
        "games": await _query(Game),
    }
