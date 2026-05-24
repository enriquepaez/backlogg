from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.people import repository as repo
from backlogg.people.schemas import PersonOut


async def get_person(db: AsyncSession, slug: str) -> PersonOut:
    """Return a PersonOut for the given slug, or raise HTTP 404."""
    person = await repo.get_person_by_slug(db, slug)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return person
