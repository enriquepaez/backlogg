from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.shared.models import Credit, Person
from backlogg.shared.schemas import CreditOut


async def get_credits_for_item(db: AsyncSession, item_type: str, item_id: int) -> list[CreditOut]:
    """Return credits for an item ordered by billing_order ascending.

    Credits without billing_order are placed last.
    """
    result = await db.execute(
        select(Credit, Person)
        .join(Person, Credit.person_id == Person.id)
        .where(Credit.item_type == item_type, Credit.item_id == item_id)
        .order_by(Credit.billing_order.asc().nulls_last())
    )
    rows = result.all()
    return [
        CreditOut(
            person_name=person.name,
            person_slug=person.slug,
            profile_url=person.profile_url,
            role=credit.role,
            character_name=credit.character_name,
            billing_order=credit.billing_order,
        )
        for credit, person in rows
    ]
