from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.search.models import CatalogSearchEntry


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        q: str,
        item_type: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        """Full-text search across the catalog_search materialized view.

        Returns (results, total) where results is a list of dicts and total is
        the count of matching rows (before pagination).

        Uses plainto_tsquery so callers do not need to escape the query string.
        Results are ordered by ts_rank descending (most relevant first).
        """
        base_stmt = select(CatalogSearchEntry).where(
            text("search_vector @@ plainto_tsquery('simple', :q)").bindparams(q=q)
        )

        if item_type is not None:
            base_stmt = base_stmt.where(CatalogSearchEntry.item_type == item_type.upper())

        # Count total matching rows
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total: int = total_result.scalar_one()

        # Fetch paginated, ranked results — ts_rank requires a raw text expression
        offset = (page - 1) * limit
        rank_expr = text("ts_rank(search_vector, plainto_tsquery('simple', :q_rank))").bindparams(
            q_rank=q
        )
        ranked_stmt = base_stmt.order_by(desc(rank_expr)).offset(offset).limit(limit)

        rows_result = await self._session.execute(ranked_stmt)
        rows = rows_result.scalars().all()

        results = [
            {
                "id": row.id,
                "item_type": row.item_type,
                "slug": row.slug,
                "title": row.title,
                "overview": row.overview,
                "poster_url": row.poster_url,
                "release_date": row.release_date,
                "rating_external": (
                    float(row.rating_external) if row.rating_external is not None else None
                ),
            }
            for row in rows
        ]

        return results, total
