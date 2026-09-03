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

__all__ = ["Base", "Person", "Credit", "SyncCursor", "SeedTarget"]


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

    ⚠️ Since feature 86 only BOOK and GAME use this table.  Movies and series
    are driven by ``seed_targets`` (below) plus a ``last_synced_at`` rotation,
    with no offset in the picture; their rows are left in place but never read
    or written again.  See ``docs/schema.md``.
    """

    __tablename__ = "sync_cursors"

    item_type: Mapped[str] = mapped_column(Text, primary_key=True)
    next_offset: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SeedTarget(Base):
    """One external item the catalog *wants*, enumerated ahead of hydration.

    Feature 86 splits enumeration from hydration.  ``/discover`` answers "which
    items clear the quality threshold" in ~3.600 cheap requests; this table
    holds that answer so the expensive part (one detail request per item) can
    be resumed, ordered and audited independently.

    Why a table and not a cursor: an offset into a listing that reorders
    itself resumes nothing (``docs/seeding-plan.md`` §1).  With the target list
    persisted, "what is left to do" is a **difference against the catalog** —
    the rows of this table with no matching ``external_ids`` row — which
    converges by construction and is correct no matter how a run died.

    ``vote_count`` and ``release_year`` are the values observed at enumeration
    time; they cost nothing (they travel in the ``/discover`` payload) and give
    the hydration a notoriety order, so an interrupted seeding run leaves the
    best of the catalog in rather than an arbitrary slice of it.

    ``attempts``/``last_attempt_at``/``unreachable_at`` are the convergence
    guard.  Some targets can never produce an ``external_ids`` row, for two
    unrelated reasons: the same ``(source, external_id)`` pair being already
    claimed by another item type (``uq_external_id`` is global across types
    while TMDB numbers movies and series in independent sequences), and the
    enumerated id simply being 404 by the time it is hydrated.  Left in the
    pending set they would occupy a slot of every nightly slice forever and
    keep "pending" permanently above zero — which would silently disable the
    ``last_synced_at`` refresh rotation and stop the backfill loop from ever
    terminating.

    So they are **retired**, not just reordered: ``unreachable_at`` records the
    404 (definitive, stamped on first observation) and ``attempts`` counts
    *conclusive* passes — a fetch that raised does not count, so an outage can
    never retire a healthy target — with retirement at
    ``settings.TMDB_SEED_MAX_ATTEMPTS``.  Retired targets are still counted and
    surfaced to the operator as ``stuck``; the ordering by ``attempts`` remains
    so that, before retirement, a struggling target drifts behind everything
    untried instead of camping at the head of the queue.
    """

    __tablename__ = "seed_targets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    vote_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unreachable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("item_type", "source", "external_id", name="uq_seed_target"),
        Index("idx_seed_targets_work_order", "item_type", "source", "attempts"),
    )
