from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

__all__ = ["ExternalId", "get_external_id", "set_external_id", "upsert_external_id"]


class ExternalId(Base):
    __tablename__ = "external_ids"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_external_id"),
        UniqueConstraint("item_type", "item_id", "source", name="uq_item_source"),
        Index("idx_external_ids_item", "item_type", "item_id"),
    )


async def get_external_id(
    db: AsyncSession, item_type: str, item_id: int, source: str
) -> ExternalId | None:
    result = await db.execute(
        select(ExternalId).where(
            ExternalId.item_type == item_type,
            ExternalId.item_id == item_id,
            ExternalId.source == source,
        )
    )
    return result.scalar_one_or_none()


async def set_external_id(
    db: AsyncSession, item_type: str, item_id: int, source: str, external_id: str
) -> ExternalId:
    record = ExternalId(
        item_type=item_type,
        item_id=item_id,
        source=source,
        external_id=external_id,
    )
    db.add(record)
    await db.flush()
    return record


async def upsert_external_id(
    db: AsyncSession, item_type: str, item_id: int, source: str, external_id: str
) -> ExternalId:
    stmt = (
        insert(ExternalId)
        .values(
            item_type=item_type,
            item_id=item_id,
            source=source,
            external_id=external_id,
        )
        .on_conflict_do_update(
            constraint="uq_item_source",
            set_={"external_id": external_id},
        )
        .returning(ExternalId)
    )
    result = await db.execute(stmt)
    await db.flush()
    row = result.scalar_one()
    # Expire the cached instance so the updated value is reflected
    await db.refresh(row)
    return row
