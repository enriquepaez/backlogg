"""Scheduler repository — persistence for slice-sync cursors.

Only this module touches SQLAlchemy for the ``sync_cursors`` table.
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.shared.models import SyncCursor

__all__ = ["get_sync_offset", "set_sync_offset"]


async def get_sync_offset(db: AsyncSession, item_type: str) -> int:
    """Return the persisted next offset for ``item_type``, or 0 if absent."""
    result = await db.execute(
        select(SyncCursor.next_offset).where(SyncCursor.item_type == item_type)
    )
    offset = result.scalar_one_or_none()
    return offset if offset is not None else 0


async def set_sync_offset(db: AsyncSession, item_type: str, next_offset: int) -> None:
    """Upsert the next offset for ``item_type`` (idempotent)."""
    stmt = (
        insert(SyncCursor)
        .values(item_type=item_type, next_offset=next_offset)
        .on_conflict_do_update(
            index_elements=[SyncCursor.item_type],
            set_={"next_offset": next_offset, "updated_at": func.now()},
        )
    )
    await db.execute(stmt)
    await db.flush()
