from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.recommendations import service
from backlogg.recommendations.schemas import RecommendationsOut, RecommendationTypeFilter
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

recommendations_router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@recommendations_router.get("", response_model=RecommendationsOut)
async def get_recommendations(
    type: RecommendationTypeFilter | None = Query(
        default=None, description="Optional content-type filter"
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    type_value = type.value if type is not None else None
    return await service.get_recommendations(
        db, user=current_user, type_filter=type_value, page=page, limit=limit
    )
