"""Admin service — business logic layer for admin domain."""

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin import repository as admin_repo
from backlogg.admin.schemas import ContentStats, StatsResponse


async def get_stats(db: AsyncSession) -> StatsResponse:
    """Return catalog stats for all 4 content types.

    Delegates the DB queries to the repository and maps the raw data
    to a StatsResponse Pydantic model.
    """
    raw = await admin_repo.get_stats(db)
    return StatsResponse(
        movies=ContentStats(**raw["movies"]),
        series=ContentStats(**raw["series"]),
        books=ContentStats(**raw["books"]),
        games=ContentStats(**raw["games"]),
    )
