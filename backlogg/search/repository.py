import logging
from datetime import date

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.search.models import CatalogSearchEntry

logger = logging.getLogger(__name__)


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def refresh_catalog_search(self) -> None:
        """Refresh the catalog_search materialized view after ingestion."""
        try:
            await self._session.execute(
                text("REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search")
            )
            await self._session.commit()
        except Exception:
            logger.exception("search fallback: failed to refresh catalog_search")

    async def search(
        self,
        q: str | None,
        item_type: str | None = None,
        page: int = 1,
        limit: int = 20,
        date_from: date | None = None,
        date_to: date | None = None,
        rating_external_min: float | None = None,
        rating_external_max: float | None = None,
    ) -> tuple[list[dict], int]:
        """Search across the catalog_search materialized view.

        Returns (results, total) where results is a list of dicts and total is
        the count of matching rows (before pagination).

        When ``q`` is provided, uses plainto_tsquery so callers do not need to
        escape the query string, and results are ordered by
        ``rating_external DESC NULLS LAST`` first (best-rated matches surface
        above unrated/lower-rated ones, even when their ts_rank is lower),
        then by ts_rank descending as a tie-breaker among items with the same
        rating (including grouping all NULL-rating items together, ordered
        among themselves by text relevance), and finally by ``id`` as the
        last tie-breaker for pagination stability (issue #14). ts_rank alone
        is not a reliable primary sort key: distinct titles rarely produce
        identical ts_rank, so a rank-first order effectively never lets
        rating_external decide (issue #14 follow-up). When ``q`` is
        ``None`` this is a pure filter query
        (``date_from``/``date_to``/``rating_external_min/max``) — the
        full-text clause is omitted entirely (there is nothing to match
        against) and results are ordered by ``rating_external DESC NULLS
        LAST`` instead, since there is no rank to sort by.
        """
        base_stmt = select(CatalogSearchEntry)

        if q is not None:
            base_stmt = base_stmt.where(
                text("search_vector @@ plainto_tsquery('simple', :q)").bindparams(q=q)
            )

        if item_type is not None:
            base_stmt = base_stmt.where(CatalogSearchEntry.item_type == item_type.upper())

        if date_from is not None:
            base_stmt = base_stmt.where(CatalogSearchEntry.release_date >= date_from)
        if date_to is not None:
            base_stmt = base_stmt.where(CatalogSearchEntry.release_date <= date_to)
        if rating_external_min is not None:
            base_stmt = base_stmt.where(CatalogSearchEntry.rating_external >= rating_external_min)
        if rating_external_max is not None:
            base_stmt = base_stmt.where(CatalogSearchEntry.rating_external <= rating_external_max)

        # Count total matching rows
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total: int = total_result.scalar_one()

        # Fetch paginated results
        offset = (page - 1) * limit
        if q is not None:
            # ts_rank requires a raw text expression. rating_external is the
            # primary sort key: ts_rank varies with title length/structure
            # even among equally relevant matches, so ordering by ts_rank
            # first means rating_external almost never gets a chance to act
            # as a tie-breaker in practice (issue #14 follow-up). ``id`` is
            # the final sort key so OFFSET/LIMIT pagination is stable across
            # requests even when rows are inserted between pages (e.g. by
            # the search fan-out).
            rank_expr = text(
                "ts_rank(search_vector, plainto_tsquery('simple', :q_rank))"
            ).bindparams(q_rank=q)
            ranked_stmt = (
                base_stmt.order_by(
                    CatalogSearchEntry.rating_external.desc().nulls_last(),
                    desc(rank_expr),
                    CatalogSearchEntry.id,
                )
                .offset(offset)
                .limit(limit)
            )
        else:
            ranked_stmt = (
                base_stmt.order_by(
                    CatalogSearchEntry.rating_external.desc().nulls_last(),
                    CatalogSearchEntry.id,
                )
                .offset(offset)
                .limit(limit)
            )

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
