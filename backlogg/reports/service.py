"""Reports service — business logic for the review reporting pipeline.

A user flags a review (a ``UserRating`` row) as problematic; admins triage the
resulting queue. Reporting is idempotent per ``(reporter, review)``: reporting
the same review twice returns the existing report instead of creating a second.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.ratings import repository as ratings_repo
from backlogg.reports import repository as repo
from backlogg.reports.schemas import ReportListOut, ReportOut


async def report_review(
    db: AsyncSession, rating_id: int, reason: str | None, reporter_id: int
) -> tuple[ReportOut, bool]:
    """File a report against review ``rating_id`` as user ``reporter_id``.

    Returns ``(report, created)``. Raises 404 if the review does not exist —
    no orphan reports. Idempotent: a repeat report returns the existing row
    with ``created=False`` so the route can answer 200 instead of 201.
    """
    review = await ratings_repo.get_rating_by_id(db, rating_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    report, created = await repo.create_report_if_not_exists(
        db, reporter_id=reporter_id, rating_id=rating_id, reason=reason
    )
    await db.commit()
    return ReportOut.model_validate(report), created


async def list_reports(
    db: AsyncSession, status: str | None, page: int, limit: int
) -> ReportListOut:
    """Admin queue: paginated reports, newest first, optionally filtered by status."""
    reports, total = await repo.list_reports(db, status, page, limit)
    items = [ReportOut.model_validate(r) for r in reports]
    return ReportListOut(items=items, total=total, page=page, limit=limit)


async def resolve_report(db: AsyncSession, report_id: int) -> ReportOut:
    """Mark a report resolved. Raises 404 if the report does not exist. Idempotent."""
    report = await repo.get_report_by_id(db, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")

    resolved = await repo.resolve_report(db, report)
    await db.commit()
    return ReportOut.model_validate(resolved)
