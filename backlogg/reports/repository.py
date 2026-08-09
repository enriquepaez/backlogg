"""Reports repository — DB queries for the review_reports table.

Only this file imports and uses SQLAlchemy for the reports domain.
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.reports.models import ReviewReport


async def create_report_if_not_exists(
    db: AsyncSession, reporter_id: int, rating_id: int, reason: str | None
) -> tuple[ReviewReport, bool]:
    """Idempotent report — INSERT ... ON CONFLICT (reporter, rating) DO NOTHING.

    Returns ``(report, created)`` where ``created`` is ``True`` when a new row
    was inserted and ``False`` when a report by the same user for the same
    review already existed. On conflict ``RETURNING`` yields no row, so the
    existing report is fetched and returned unchanged (the original ``reason``
    is preserved — a repeat report never overwrites it).
    """
    stmt = (
        pg_insert(ReviewReport)
        .values(reporter_id=reporter_id, rating_id=rating_id, reason=reason)
        .on_conflict_do_nothing(constraint="uq_review_report_pair")
        .returning(ReviewReport.id)
    )
    result = await db.execute(stmt)
    new_id = result.scalar_one_or_none()
    await db.flush()

    if new_id is not None:
        row = await db.execute(select(ReviewReport).where(ReviewReport.id == new_id))
        return row.scalar_one(), True

    existing = await db.execute(
        select(ReviewReport).where(
            ReviewReport.reporter_id == reporter_id, ReviewReport.rating_id == rating_id
        )
    )
    return existing.scalar_one(), False


async def get_report_by_id(db: AsyncSession, report_id: int) -> ReviewReport | None:
    result = await db.execute(select(ReviewReport).where(ReviewReport.id == report_id))
    return result.scalar_one_or_none()


async def list_reports(
    db: AsyncSession, status: str | None, page: int, limit: int
) -> tuple[list[ReviewReport], int]:
    """Paginated report queue, newest first, optionally filtered by status."""
    filters = []
    if status is not None:
        filters.append(ReviewReport.status == status)

    count_result = await db.execute(select(func.count()).select_from(ReviewReport).where(*filters))
    total = count_result.scalar_one()

    paged_stmt = (
        select(ReviewReport)
        .where(*filters)
        .order_by(ReviewReport.created_at.desc(), ReviewReport.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(paged_stmt)
    return list(result.scalars().all()), total


async def resolve_report(db: AsyncSession, report: ReviewReport) -> ReviewReport:
    """Mark a report as resolved and stamp ``resolved_at``. Idempotent."""
    if report.status != "resolved":
        report.status = "resolved"
        report.resolved_at = func.now()
        await db.flush()
        await db.refresh(report)
    return report
