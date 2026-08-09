from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin.auth import verify_api_key
from backlogg.core.database import get_db
from backlogg.reports import service
from backlogg.reports.schemas import (
    ReportListOut,
    ReportOut,
    ReportReasonIn,
    ReportStatus,
)
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

# User-facing endpoint: report a review by id. Its own "/reviews" prefix keeps
# it independent of the content routers (a review is not scoped to one type).
reports_router = APIRouter(prefix="/reviews", tags=["reports"])

# Admin moderation queue. Same X-API-Key gate and "/admin" prefix as
# backlogg.admin.router, applied at the router level.
admin_reports_router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(verify_api_key)]
)


@reports_router.post(
    "/{rating_id}/report",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Report a review",
    description=(
        "Flag a review as problematic. Idempotent per (reporter, review): the "
        "first report returns 201, a repeat returns 200 with the existing "
        "report. 404 if the review does not exist, 401 without auth."
    ),
)
async def report_review(
    rating_id: int,
    response: Response,
    payload: ReportReasonIn | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportOut:
    reason = payload.reason if payload is not None else None
    report, created = await service.report_review(
        db, rating_id=rating_id, reason=reason, reporter_id=current_user.id
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return report


@admin_reports_router.get(
    "/reports",
    response_model=ReportListOut,
    summary="List review reports",
    description=(
        "Paginated moderation queue, newest first, filterable by status. Requires `X-API-Key`."
    ),
)
async def list_reports(
    status: ReportStatus | None = Query(default=None, description="Filter by report status"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> ReportListOut:
    return await service.list_reports(
        db, status=status.value if status is not None else None, page=page, limit=limit
    )


@admin_reports_router.post(
    "/reports/{report_id}/resolve",
    response_model=ReportOut,
    summary="Resolve a review report",
    description="Mark a report as resolved. Idempotent. 404 if unknown. Requires `X-API-Key`.",
)
async def resolve_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReportOut:
    return await service.resolve_report(db, report_id=report_id)
