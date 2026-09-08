from datetime import datetime
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backlogg.core.database import Base
from backlogg.shared.codes import CreditRoleCode, ItemTypeCode

__all__ = [
    "Base",
    "Person",
    "Credit",
    "ItemCast",
    "SyncCursor",
    "SeedTarget",
    "SyncWatermark",
]


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
    """The **navigation graph** between people and items — no longer the cast.

    Feature 89 split this table in two.  What stays here is what earns a
    relational row: ``DIRECTOR``, ``CREATOR``, ``WRITER``, ``AUTHOR`` and
    ``SOURCE_AUTHOR`` — the roles that answer "other works by this person" and
    carry the cross-type authorship bridge of feature 74.  The cast moved to
    ``ItemCast``: it was 72,8 % of the rows and 175.306 of the 240.615 people,
    almost all of them appearing exactly once, for a datum that is only ever
    read as a block on the detail page of one item.  See ``docs/schema.md``.

    Three consequences of that split are visible right here:

    * **No surrogate ``id``.**  Nothing ever referenced it (verified: zero FKs
      against ``credits.id`` in production), and ``uq_credit`` was already the
      identity of a row, so the column plus its primary-key index were 20 MB
      spent on a duplicate key.  The natural key is now the primary key.
    * **Column order is load-bearing.**  ``item_id`` and ``person_id``
      (``bigint``, 8-byte aligned) come *before* the two ``smallint``s on
      purpose.  Declaring the ``smallint`` first would make Postgres insert 6
      bytes of alignment padding after it in every row — ~7 MB across the
      table and the same again inside the primary key, for nothing.  The key
      is ordered the same way for the same reason.
    * **No ``character_name`` / ``billing_order``.**  Measured in production:
      zero non-``ACTOR`` rows carried a value in either column.  They were
      cast columns, and the cast lives in ``ItemCast`` now.
    """

    __tablename__ = "credits"

    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    person_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    item_type: Mapped[str] = mapped_column(ItemTypeCode, primary_key=True)
    role: Mapped[str] = mapped_column(CreditRoleCode, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    person: Mapped[Person] = relationship("Person", back_populates="credits")

    __table_args__ = (
        Index("idx_credits_person", "person_id"),
        Index("idx_credits_item", "item_type", "item_id"),
        Index("idx_credits_role", "role"),
    )


class ItemCast(Base):
    """The cast of one catalog item, denormalised into a single JSONB array.

    Feature 89.  The cast is *detail-page data*: it is read whole, always for
    one known item, and nobody navigates out of the seventh billed actor.  It
    was paying a row in ``people``, a row in ``external_ids``, a row in
    ``credits`` and a slice of seven indexes per actor to buy navigation that
    does not exist.  Here it costs one row per item — 642 B on average,
    comfortably under the ~2 kB TOAST threshold, so it stays inline and
    uncompressed and the detail page reads it in the same page fetch.

    **A side table, not a column of ``movies``/``series``** (decision of
    2026-09-07): the detail page reads the cast, but search and trending scan
    the item tables end to end without ever touching it.  Widening every item
    row by ~642 B (+40 % on ``movies``) would make those scans pay for a
    lookup by primary key the detail page can afford.

    ``payload`` is an array ordered by billing order, **never truncated** — the
    detail page keeps showing the full cast (9,31 actors on average, 30 at the
    most).  Keys are one character because their bytes are repeated ~518.000
    times and payload size is the entire point of the feature:

    ``[{"n": "Timothée Chalamet", "c": "Paul Atreides", "o": 0}, ...]``

    ``c`` (character) and ``o`` (billing order) are omitted when unknown; ``n``
    (name) is always there.  See ``backlogg.shared.credits`` for the single
    pair of functions that build and read this shape.
    """

    __tablename__ = "item_cast"

    item_type: Mapped[str] = mapped_column(ItemTypeCode, primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payload: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


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
    unrelated reasons: the fetch resolving without the item ever getting linked
    (two TMDB ids whose title and year slugify to the same value share one row
    and only one of them keeps its link; until migration 0036 there was a much
    more common shape — ``uq_external_id`` had no ``item_type``, so a PERSON id
    blocked the movie or series with the same number, issue #20), and the
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


class SyncWatermark(Base):
    """Where each incremental mechanism left off, per source and per mechanism.

    Feature 88 stops maintaining the catalog by re-walking full listings and
    starts asking every source *what changed since last time*.  That question
    needs a persisted answer to "last time", and neither of the two existing
    state tables can give it:

    - ``sync_cursors`` holds a **numeric offset** into a listing
      (``next_offset``).  It answers "how far down the page am I", not "up to
      which instant have I already seen the world".  Its ``updated_at`` is a
      row-touch timestamp, not a cut-off: it moves when the row is written,
      which is *after* the window was queried, so resuming from it would
      silently drop everything that happened while the run was running.
    - ``seed_targets`` is a **work list by difference** against the catalog.
      It converges without any cursor precisely because it is stateless in
      time — which is its strength for hydration and exactly why it cannot
      express "ask TMDB for the changes of the last N days".

    Shape of the key: ``(source, kind, item_type)``
    ----------------------------------------------

    The watermark is per source *and* per mechanism, because two mechanisms of
    the same source advance independently and can fail independently.  These
    are the rows the incremental actually writes:

    ========== ==================== ========= ==========================
    source     kind                 item_type cursor_value holds
    ========== ==================== ========= ==========================
    TMDB       ``DAILY_ID_EXPORT``  MOVIE     date of the export file
    TMDB       ``DAILY_ID_EXPORT``  SERIES    date of the export file
    TMDB       ``CHANGES``          MOVIE     last instant covered
    TMDB       ``CHANGES``          SERIES    last instant covered
    IGDB       ``CREATED_AT``       GAME      last ``created_at`` covered
    IGDB       ``UPDATED_AT``       GAME      last ``updated_at`` covered
    OPEN_LIBR. ``MONTHLY_DUMP``     BOOK      edition of the dump diffed
    ========== ==================== ========= ==========================

    All three parts are load-bearing.  ``source`` alone collapses the two TMDB
    mechanisms, which is wrong: ``/changes`` can be 5 days behind while the
    daily export is current, and resuming either from the other's cut-off
    loses or re-does work.  ``(source, kind)`` alone collapses movies and
    series, which run as two separate passes against two separate endpoints
    and, being independent, can end a night at different points.  ``item_type``
    is the third axis and nothing smaller works.

    ``item_type`` is **NOT NULL** even for mechanisms that only serve one type.
    A nullable column inside the key would be a real bug and not just a
    modelling preference: Postgres treats NULLs as distinct in a unique index,
    so ``INSERT ... ON CONFLICT`` would never match an existing row and every
    run would append a duplicate instead of advancing the watermark.  So
    Open Library writes ``BOOK`` explicitly.

    Why two columns and not one
    ---------------------------

    ``last_run_at`` (when the mechanism last completed successfully) and
    ``cursor_value`` (the cut-off the *next* run must use) look redundant and
    are not.  They differ in two independent ways:

    1. **They are not the same clock.**  A run that queried up to instant *T*
       and finished at *T+9min* must resume at *T*: resuming at its own
       finish time drops the changes of those 9 minutes for good.  And the
       daily ID export is published around 08:00 UTC, so a run at 00:10 UTC
       processes *yesterday's* file — deriving the next cut-off from the run's
       clock would skip a day or re-read one.
    2. **They are not the same type.**  For ``CHANGES`` and the two IGDB kinds
       the cut-off is an instant; for ``DAILY_ID_EXPORT`` it is the date of the
       file already processed; for ``MONTHLY_DUMP`` it is which dump edition
       was diffed.  ``cursor_value`` is therefore ``Text``, opaque to this
       layer and parsed by the mechanism that wrote it (ISO-8601 in every case
       so it sorts and reads sanely), instead of a ``timestamptz`` that would
       force a fake midnight on a file date and a fake instant on a dump
       edition.

    ``last_run_at`` earns its place on the operational side: it is the freshness
    signal ("did the incremental run last night?") and, for ``CHANGES``, the
    input to the 14-day gap check — TMDB only answers for the last 14 days, so
    a mechanism whose watermark is older than that has a hole that ``/changes``
    can no longer fill and only the full sweep can (see
    ``backlogg.scheduler.discovery.plan_change_windows``).

    ``cursor_value`` is nullable so a row can exist for a mechanism that ran
    but produced no usable cut-off yet (a first pass that found nothing), which
    is different from the mechanism never having run at all — that is simply
    the absence of the row.
    """

    __tablename__ = "sync_watermarks"

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    item_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    cursor_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
