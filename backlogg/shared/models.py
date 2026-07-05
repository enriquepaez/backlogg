from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backlogg.core.database import Base

__all__ = ["Base", "Person", "Credit", "SyncCursor"]


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    profile_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    credits: Mapped[list["Credit"]] = relationship("Credit", back_populates="person")

    __table_args__ = (Index("idx_people_last_synced_at", "last_synced_at"),)


class Credit(Base):
    __tablename__ = "credits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    character_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    person: Mapped[Person] = relationship("Person", back_populates="credits")

    __table_args__ = (
        UniqueConstraint("item_type", "item_id", "person_id", "role", name="uq_credit"),
        Index("idx_credits_person", "person_id"),
        Index("idx_credits_item", "item_type", "item_id"),
        Index("idx_credits_role", "role"),
    )


class SyncCursor(Base):
    """Persisted per-type offset for slice-based nightly sync.

    ``item_type`` matches the polymorphic values used across the app
    (MOVIE, SERIES, BOOK, GAME).  ``next_offset`` is where the next sync
    run should start fetching from the external API's popular listing.
    """

    __tablename__ = "sync_cursors"

    item_type: Mapped[str] = mapped_column(Text, primary_key=True)
    next_offset: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
