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
        # Unique **per item type**: TMDB numbers movies, series and people in
        # independent sequences that overlap, so id 110531 can legitimately be
        # both a person and a series.  Leaving ``item_type`` out of this key
        # made the first claimant of a number block every other type from ever
        # being linked — silently, since both upsert paths pre-check and skip
        # (issue #20).
        UniqueConstraint("item_type", "source", "external_id", name="uq_external_id"),
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
    # Check first if this (item_type, source, external_id) triple already
    # exists. Prevents uq_external_id IntegrityError when the same external ID
    # appears more than once (e.g. same TMDB person in cast and crew).
    #
    # ``item_type`` is part of the lookup because it is part of the constraint:
    # without it, a PERSON row claiming TMDB id 110531 made the *series* 110531
    # unlinkable forever, and this pre-check returned that unrelated PERSON row
    # instead of raising (issue #20). Two items of *different* types may now
    # share a number; two items of the *same* type still may not, and for that
    # case the pre-check keeps its original semantics — first claim wins.
    existing_check = await db.execute(
        select(ExternalId).where(
            ExternalId.item_type == item_type,
            ExternalId.source == source,
            ExternalId.external_id == external_id,
        )
    )
    existing_row = existing_check.scalar_one_or_none()
    if existing_row is not None:
        # Already linked to an item of this type. If it points to the same
        # item, return as-is. If it points to a different item (item_id
        # mismatch), keep the first claim to preserve data integrity.
        return existing_row

    # Not yet linked — safe to insert.
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
    await db.refresh(row)
    return row
