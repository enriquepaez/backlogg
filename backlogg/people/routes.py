from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.people import service
from backlogg.people.schemas import PersonOut

router = APIRouter(prefix="/people", tags=["people"])


@router.get(
    "/{slug}",
    response_model=PersonOut,
    summary="Get person detail",
    description="A person (cast or crew) with their credits across the catalog.",
)
async def get_person(slug: str, db: AsyncSession = Depends(get_db)):
    return await service.get_person(db, slug)
