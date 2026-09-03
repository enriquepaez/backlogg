"""Batch write path for massive catalog ingestion (feature 84).

The per-item write path (``upsert_movie`` + ``upsert_external_id`` +
``_persist_movie_people`` + two commits) costs 35-75 SQL round trips *per
item*.  Against Neon (~40 ms per round trip) that is the 3,1 s/item measured
in the real backfill run 32937145403, i.e. ~102 h for a 100k catalog.  This
module replaces those per-item round trips with a fixed, small number of
round trips *per batch*:

    CREATE TEMP TABLE ... ON COMMIT DROP     (one per staged relation)
    COPY records -> temp table               (asyncpg binary COPY)
    INSERT INTO <real> SELECT ... FROM <temp> ON CONFLICT ...

plus a single ``SELECT ... WHERE (item_type, source, external_id) IN (...)``
that resolves *every* person of the batch at once, replacing the
``get_person_id_by_external`` + ``get_person_by_id`` pair that the per-item
route issues for each of the ~7 credits of every item.

Everything runs on the ``AsyncSession``'s own connection: the raw asyncpg
connection is borrowed from the session (``session.connection()`` ->
``get_raw_connection().driver_connection``) so the COPY participates in the
*same* transaction as the rest of the batch.  Nothing is committed here —
committing is the caller's decision.

Driver note: the project is asyncpg-only (no psycopg anywhere), so the COPY
API available is ``asyncpg.Connection.copy_records_to_table``.  Every primary
key in the schema is a ``BigInteger`` identity column, so records cannot be
COPYed straight into the real tables (the ids do not exist yet): they go to a
temp table keyed by the *natural* key (slug, or the unique tuple of a credit)
and the real ids come back from ``INSERT ... SELECT ... ON CONFLICT ...
RETURNING``.

Failure semantics (feature 84, acceptance #4) — deliberate, two levels
-----------------------------------------------------------------------

1. **A single invalid row is dropped, never the batch.**  Postgres aborts a
   whole COPY on the first bad row, so validation *has* to happen before the
   COPY.  Every row is checked in Python against the target table's real
   contract (NOT NULL columns, ``String(n)`` lengths, integer ranges,
   ``Numeric(p, s)`` range, dates already converted to ``date``/``datetime``)
   and coerced to the exact Python type asyncpg's binary COPY expects.  A row
   that fails is logged (``logger.warning`` with the natural key and the
   reason) and counted in ``BulkLoadResult.rejected``; the rest of the batch
   is written normally.  Invalid credit rows are dropped the same way and
   counted in ``BulkLoadResult.people_rejected`` — a bad credit never costs
   an item.

   The regression this rules out is the one that matters: a single malformed
   row taking 1.000 good items down with it, which is exactly what the
   per-item route does *not* do today.

2. **If the batch itself fails, the caller falls back to the per-item
   route.**  Anything unexpected (an IntegrityError this module did not
   anticipate, a deadlock, a concurrent writer) raises out of
   ``bulk_load_items``.  The caller
   (``backlogg.scheduler.jobs._write_batch``) rolls the batch back and
   reprocesses the same items through the unchanged per-item path, which
   keeps its own per-item isolation (``rollback_quietly``).  So the worst
   case of the batch route is "as slow as today", never "data lost".

Batch size ceiling (``BULK_LOAD_BATCH_SIZE``)
--------------------------------------------

Everything here is O(1) round trips per batch *except* two lookups that are
rendered as ``tuple_(...).in_(...)``: the person resolution in
``_resolve_people`` and the claim pre-check in ``_upsert_external_ids``.  Both
key on ``(item_type, source, external_id)`` since issue #20 put ``item_type``
into ``uq_external_id``, so both spend **3 bind parameters per key**, and
Postgres' extended query protocol caps a single statement at **32.767
parameters** (the count is a signed 16-bit field on the wire).

With the default of 500 items and the ~7 credits/item this catalog averages,
``_resolve_people`` renders ~3.500 keys = ~10.500 parameters — still
comfortably below the cap.  The cliff moved from ~2.300 to **~1.560 items per
batch** at 7 credits/item (32.767 / 3 / 7); an item type with fatter credit
lists reaches it sooner, so the real bound is on *keys*, not on items.

Crossing it is not a correctness problem — the statement raises, the batch
raises with it, and ``_write_batch`` reprocesses those items through the
per-item route, so no data is lost.  But that fallback is ~50x slower and
announces itself only in the log, so an over-eager ``BULK_LOAD_BATCH_SIZE``
degrades into a silent slowdown rather than an obvious failure.  Do not raise
it past ~1.400 without splitting those two lookups into chunks first.

The on-demand path (``GET /movies/{slug}`` and friends) is deliberately left
untouched: it writes one item and would gain nothing from batching.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import Table, select, text, tuple_
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import sqltypes

from backlogg.shared.external_ids import ExternalId
from backlogg.shared.models import Credit, Person

logger = logging.getLogger(__name__)

__all__ = [
    "BulkItem",
    "BulkLoadError",
    "BulkLoadResult",
    "BulkLoadSpec",
    "BulkPerson",
    "EntityCreditSpec",
    "LookupJoinSpec",
    "bulk_load_credits",
    "bulk_load_items",
    "copy_round_trips",
    "rollback_quietly",
]

# Columns that ON CONFLICT DO UPDATE never overwrites, mirroring the per-item
# upserts (``rating_count_internal`` belongs to the community, not to the
# external source; ``slug``/``created_at``/``id`` are identity).
_NEVER_UPDATED = frozenset({"id", "slug", "created_at", "rating_count_internal"})

_PG_DIALECT = postgresql.dialect()

# COPY is the one round trip SQLAlchemy's ``before_cursor_execute`` cannot
# see: it is issued straight on the raw asyncpg connection.  Everything else
# (including the temp-table DDL) goes through the session, so
# ``scripts/bench_bulk_load.py`` only has to add this counter to the
# SQLAlchemy count to get the real number of round trips per batch.
copy_round_trips: dict[str, int] = {"copy": 0}


# ── Public data shapes ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BulkPerson:
    """One person + their credit on the item being loaded.

    ``source``/``external_id`` are the person's identity in the external API
    (``("TMDB", "287")``); they are what the single batch lookup resolves.
    """

    source: str
    external_id: str
    name: str
    slug: str
    profile_url: str | None
    role: str
    character_name: str | None = None
    billing_order: int | None = None


@dataclass(slots=True)
class BulkItem:
    """One catalog item to write: its columns, its external id and its people.

    ``data`` is the same dict the per-item repositories take (``movie_to_dict``
    output), including the ``genres``/``platforms``/``companies`` lists — the
    spec declares which keys are relations so they are not mistaken for
    columns.  ``data`` is never mutated.
    """

    data: dict[str, Any]
    external_id: str | None = None
    people: list[BulkPerson] = field(default_factory=list)


@dataclass(slots=True)
class BulkLoadResult:
    """Outcome of one batch. ``rejected`` counts pre-validation drops."""

    written: int = 0
    rejected: int = 0
    people_written: int = 0
    people_rejected: int = 0

    def merge(self, other: BulkLoadResult) -> None:
        self.written += other.written
        self.rejected += other.rejected
        self.people_written += other.people_written
        self.people_rejected += other.people_rejected


# ── Spec: what makes one content type different from another ─────────────────


@dataclass(frozen=True, slots=True)
class LookupJoinSpec:
    """A many-to-many relation resolved by slug (genres, platforms).

    ``lockable`` mirrors feature 49: when the item's ``locked_fields`` contain
    ``data_key`` the relation is left exactly as the admin left it.
    """

    data_key: str
    lookup_table: Table
    lookup_columns: tuple[str, ...]
    join_table: Table
    item_column: str
    lookup_column: str
    lockable: bool = True


@dataclass(frozen=True, slots=True)
class EntityCreditSpec:
    """A credit against a non-person entity resolved by slug (game companies).

    Same shape as people/credits but the entity has no external id: the slug
    is its identity.  ``entity_defaults`` fills NOT NULL columns the source
    payload does not carry (``companies.last_synced_at``).
    """

    data_key: str
    entity_table: Table
    entity_columns: tuple[str, ...]
    entity_defaults: tuple[tuple[str, Callable[[], Any]], ...]
    credit_table: Table
    entity_fk: str
    constraint: str


@dataclass(frozen=True, slots=True)
class BulkLoadSpec:
    """Everything the generic loader needs to know about one content type."""

    item_type: str
    source: str
    table: Table
    upsert_item: Callable[[AsyncSession, dict], Any]
    lookups: tuple[LookupJoinSpec, ...] = ()
    entity_credits: tuple[EntityCreditSpec, ...] = ()

    @property
    def relation_keys(self) -> frozenset[str]:
        return frozenset(
            [lookup.data_key for lookup in self.lookups]
            + [entity.data_key for entity in self.entity_credits]
        )


# ── Validation / coercion ────────────────────────────────────────────────────


class RowRejected(ValueError):
    """A row failed pre-validation and must be dropped, not COPYed."""


class BulkLoadError(RuntimeError):
    """The batch as a whole did not land as intended — fall back per item."""


def _coerce(col: Any, value: Any) -> Any:
    """Return ``value`` as the exact Python type asyncpg's COPY expects.

    Raises ``RowRejected`` when the value cannot legally reach the column —
    that is the whole point: Postgres would abort the entire COPY, so the row
    has to be caught here instead.
    """
    type_ = col.type
    if value is None:
        if not col.nullable:
            raise RowRejected(f"{col.name}: NULL in a NOT NULL column")
        return None

    if isinstance(type_, sqltypes.DateTime):
        if not isinstance(value, datetime):
            raise RowRejected(f"{col.name}: expected datetime, got {type(value).__name__}")
        if type_.timezone and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    if isinstance(type_, sqltypes.Date):
        if isinstance(value, datetime):
            return value.date()
        if not isinstance(value, date):
            raise RowRejected(f"{col.name}: expected date, got {type(value).__name__}")
        return value

    if isinstance(type_, sqltypes.String):
        if not isinstance(value, str):
            raise RowRejected(f"{col.name}: expected str, got {type(value).__name__}")
        if type_.length is not None and len(value) > type_.length:
            raise RowRejected(f"{col.name}: {len(value)} chars exceeds VARCHAR({type_.length})")
        return value

    if isinstance(type_, sqltypes.Integer):
        if isinstance(value, bool):
            raise RowRejected(f"{col.name}: expected int, got bool")
        if isinstance(value, int):
            as_int = value
        elif isinstance(value, float) and value.is_integer():
            as_int = int(value)
        else:
            raise RowRejected(f"{col.name}: expected int, got {type(value).__name__}")
        if isinstance(type_, sqltypes.BigInteger):
            low, high = -(2**63), 2**63 - 1
        elif isinstance(type_, sqltypes.SmallInteger):
            low, high = -(2**15), 2**15 - 1
        else:
            low, high = -(2**31), 2**31 - 1
        if not low <= as_int <= high:
            raise RowRejected(f"{col.name}: {as_int} out of range for {type_.__class__.__name__}")
        return as_int

    if isinstance(type_, sqltypes.Numeric):
        try:
            as_dec = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise RowRejected(f"{col.name}: not a number ({value!r})") from exc
        if not as_dec.is_finite():
            raise RowRejected(f"{col.name}: non-finite number ({value!r})")
        scale = type_.scale
        precision = type_.precision
        if scale is not None:
            as_dec = as_dec.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
        if precision is not None and scale is not None:
            if abs(as_dec) >= Decimal(10) ** (precision - scale):
                raise RowRejected(f"{col.name}: {as_dec} overflows NUMERIC({precision},{scale})")
        return as_dec

    if isinstance(type_, postgresql.ARRAY):
        if not isinstance(value, list | tuple):
            raise RowRejected(f"{col.name}: expected a list, got {type(value).__name__}")
        return list(value)

    return value


def _python_default(col: Any) -> Any:
    """The scalar default SQLAlchemy would apply, or ``None`` if there is none.

    The batch route writes with raw SQL, so *client-side* column defaults
    (``rating_count_internal``'s ``default=0``) never fire on their own — they
    have to be materialised here or the INSERT would violate the NOT NULL.
    Only scalar defaults are honoured: a callable default takes an execution
    context this module has no business faking, so a row missing one is
    rejected instead (see ``_required_columns``).
    """
    default = col.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    return default.arg


def _defaulted_columns(table: Table) -> tuple[str, ...]:
    """NOT NULL columns whose value comes from a scalar client-side default.

    They must be part of the COPY even when the payload omits them.
    """
    return tuple(
        col.name
        for col in table.columns
        if not col.nullable and col.server_default is None and _python_default(col) is not None
    )


def _required_columns(table: Table) -> frozenset[str]:
    """NOT NULL columns a row must carry because nothing else can fill them.

    A column with a *server* default (``created_at``) is filled by Postgres,
    and one with a scalar client-side default is filled by
    ``_python_default``; everything else NOT NULL has to be in the payload.
    """
    return frozenset(
        col.name
        for col in table.columns
        if not col.nullable
        and col.server_default is None
        and _python_default(col) is None
        and not (col.primary_key and col.autoincrement)
    )


def _build_record(table: Table, columns: Sequence[str], data: dict[str, Any]) -> tuple:
    """Validate + coerce ``data`` into a COPY record for ``columns``.

    Raises ``RowRejected`` with a human-readable reason.
    """
    missing = _required_columns(table) - set(data)
    if missing:
        raise RowRejected(f"missing required columns: {', '.join(sorted(missing))}")
    record = []
    for name in columns:
        if name not in table.c:
            raise RowRejected(f"{name}: not a column of {table.name}")
        col = table.c[name]
        value = data[name] if name in data else _python_default(col)
        record.append(_coerce(col, value))
    return tuple(record)


# ── COPY plumbing ────────────────────────────────────────────────────────────


async def _raw_asyncpg_connection(session: AsyncSession) -> Any:
    """Return the asyncpg connection backing ``session``'s transaction.

    Going through ``session.connection()`` (instead of the engine) is what
    keeps the COPY inside the session's transaction — including a test's
    outer SAVEPOINT, so the suite stays isolated.
    """
    sa_connection = await session.connection()
    fairy = await sa_connection.get_raw_connection()
    return fairy.driver_connection


def _temp_table_ddl(table: Table, columns: Sequence[str], temp_name: str) -> str:
    """DDL for an unconstrained temp mirror of ``columns`` of ``table``."""
    rendered = ", ".join(
        f'"{name}" {table.c[name].type.compile(dialect=_PG_DIALECT)}' for name in columns
    )
    return f'CREATE TEMP TABLE "{temp_name}" ({rendered}) ON COMMIT DROP'


class _Staging:
    """Creates the temp tables a batch needs and COPYs the records into them.

    The ``CREATE TEMP TABLE`` goes through the **session**, not the raw
    connection: SQLAlchemy opens its transaction lazily, on the first
    statement it issues itself, and ``ON COMMIT DROP`` outside a transaction
    block means the table is dropped by the implicit commit of its own CREATE
    — the following INSERT would then fail with "relation does not exist".
    Going through the session guarantees the transaction is open, and the COPY
    that follows on the raw connection therefore lands *inside* it.

    Temp table names carry a random suffix: ``ON COMMIT DROP`` only fires on a
    real COMMIT, and under the test fixture's SAVEPOINT-based isolation a
    ``session.commit()`` is only a savepoint release, so a fixed name would
    collide between two batches inside one test.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._pending: list[tuple[str, str, list[str], list[tuple]]] = []

    def add(self, table: Table, columns: Sequence[str], records: list[tuple]) -> str:
        temp_name = f"_bulk_{table.name}_{uuid4().hex[:12]}"
        ddl = _temp_table_ddl(table, columns, temp_name)
        self._pending.append((temp_name, ddl, list(columns), records))
        return temp_name

    async def flush(self) -> None:
        """Create every pending temp table and COPY its records into it."""
        if not self._pending:
            return
        for _, ddl, _, _ in self._pending:
            await self._session.execute(text(ddl))
        connection = await _raw_asyncpg_connection(self._session)
        for temp_name, _, columns, records in self._pending:
            await connection.copy_records_to_table(temp_name, records=records, columns=columns)
            copy_round_trips["copy"] += 1
        self._pending.clear()


def _quoted(names: Iterable[str]) -> str:
    return ", ".join(f'"{name}"' for name in names)


async def _insert_from_temp(
    session: AsyncSession,
    table: Table,
    columns: Sequence[str],
    temp_name: str,
    *,
    conflict: str,
    returning: Sequence[str] = (),
) -> list[Any]:
    """``INSERT INTO table (cols) SELECT cols FROM temp <conflict> [RETURNING]``."""
    column_list = _quoted(columns)
    sql = (
        f'INSERT INTO "{table.name}" ({column_list}) '
        f'SELECT {column_list} FROM "{temp_name}" {conflict}'
    )
    if returning:
        sql += f" RETURNING {_quoted(returning)}"
    result = await session.execute(text(sql))
    return list(result.all()) if returning else []


def _locked_aware_update(table: Table, columns: Sequence[str]) -> str:
    """``DO UPDATE SET`` clause honouring per-field admin locks (feature 49).

    Same CASE-per-column rule as ``upsert_movie``: a column listed in the
    target row's ``locked_fields`` keeps its own value instead of taking the
    proposed one.
    """
    has_locks = "locked_fields" in table.c
    assignments = []
    for name in columns:
        if name in _NEVER_UPDATED:
            continue
        if has_locks:
            # Both sides are cast to text[]: locked_fields is VARCHAR[] and a
            # bare ARRAY['title'] literal is text[], and Postgres has no
            # varchar[] @> text[] operator.
            assignments.append(
                f'"{name}" = CASE WHEN "{table.name}"."locked_fields"::text[] '
                f"@> ARRAY['{name}']::text[] "
                f'THEN "{table.name}"."{name}" ELSE excluded."{name}" END'
            )
        else:
            assignments.append(f'"{name}" = excluded."{name}"')
    if not assignments:
        # Nothing to refresh (payload is identity-only): keep the row as-is.
        return f'"slug" = "{table.name}"."slug"'
    return ", ".join(assignments)


# ── Generic sub-loaders ──────────────────────────────────────────────────────


async def _load_lookup_rows(
    session: AsyncSession,
    staging: _Staging,
    table: Table,
    columns: Sequence[str],
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert lookup rows (genres/platforms/companies) and return slug -> id.

    The slug is the lookup's real identity, exactly like
    ``_get_or_create_genre``: two source spellings that slugify to the same
    value must resolve to the same row.

    The conflict action is ``DO UPDATE SET "slug" = excluded."slug"`` — a
    self-assignment, so the pre-existing row is preserved byte for byte — and
    **not** ``DO NOTHING``.  The difference matters under concurrency:
    ``DO NOTHING`` does not wait for an uncommitted concurrent insert of the
    same slug and returns no row for it, and a follow-up ``SELECT`` would not
    see that row either, so the slug would silently drop out of the mapping
    and the item would lose that genre.  ``DO UPDATE`` blocks on the other
    writer and always yields a row, so ``RETURNING`` alone resolves the ids of
    both the new and the pre-existing rows — which also saves the SELECT.
    """
    if not rows:
        return {}
    records = []
    seen: set[str] = set()
    for row in rows:
        slug = row.get("slug")
        if not isinstance(slug, str) or not slug or slug in seen:
            continue
        try:
            records.append(_build_record(table, columns, row))
        except RowRejected as exc:
            logger.warning("bulk_load: dropping %s row %r — %s", table.name, slug, exc)
            continue
        seen.add(slug)
    if not records:
        return {}
    temp_name = staging.add(table, columns, records)
    await staging.flush()
    returned = await _insert_from_temp(
        session,
        table,
        columns,
        temp_name,
        conflict='ON CONFLICT ("slug") DO UPDATE SET "slug" = excluded."slug"',
        returning=("id", "slug"),
    )
    return {slug: row_id for row_id, slug in returned}


async def _replace_join_rows(
    session: AsyncSession,
    staging: _Staging,
    join_spec: LookupJoinSpec,
    item_ids: list[int],
    pairs: list[tuple[int, int]],
) -> None:
    """Re-sync a join table for ``item_ids``: delete then insert the pairs.

    Delete-then-insert is the per-item repositories' semantics (the source's
    list is authoritative), just done once for the whole batch.
    """
    join_table = join_spec.join_table
    if not item_ids:
        return
    await session.execute(
        text(f'DELETE FROM "{join_table.name}" WHERE "{join_spec.item_column}" = ANY(:ids)'),
        {"ids": item_ids},
    )
    unique_pairs = sorted(set(pairs))
    if not unique_pairs:
        return
    columns = (join_spec.item_column, join_spec.lookup_column)
    temp_name = staging.add(join_table, columns, unique_pairs)
    await staging.flush()
    await _insert_from_temp(
        session, join_table, columns, temp_name, conflict="ON CONFLICT DO NOTHING"
    )


async def _upsert_external_ids(
    session: AsyncSession,
    staging: _Staging,
    rows: list[tuple[str, int, str, str]],
) -> None:
    """Batch equivalent of ``upsert_external_id`` for a whole slice.

    Reproduces the per-item semantics exactly:

    * an ``(item_type, source, external_id)`` triple already claimed by
      another row **of the same type** is left alone — first claim wins (that
      pre-check is why the per-item helper exists at all: the same TMDB person
      shows up in cast and crew);
    * otherwise insert, and on ``uq_item_source`` update the external id.

    The pre-check keys on ``item_type`` because ``uq_external_id`` does
    (issue #20). Comparing ``(source, external_id)`` alone made a PERSON row
    holding TMDB id 110531 swallow the *series* 110531 without an exception, a
    counter or a log line — 0,93% of the enumerated 2022 series measured
    against the dev database, and growing with the size of ``people``.

    Within the batch the same two rules are applied as de-duplication: first
    wins on ``(item_type, source, external_id)``, last wins on
    ``(item_type, item_id, source)`` — the order a sequential per-item run
    would produce.
    """
    if not rows:
        return
    by_pair: dict[tuple[str, str, str], tuple[str, int, str, str]] = {}
    for row in rows:
        by_pair.setdefault((row[0], row[2], row[3]), row)
    by_item: dict[tuple[str, int, str], tuple[str, int, str, str]] = {}
    for row in by_pair.values():
        by_item[(row[0], row[1], row[2])] = row

    candidates = list(by_item.values())
    keys = [(row[0], row[2], row[3]) for row in candidates]
    existing = await session.execute(
        select(ExternalId.item_type, ExternalId.source, ExternalId.external_id).where(
            tuple_(ExternalId.item_type, ExternalId.source, ExternalId.external_id).in_(keys)
        )
    )
    claimed = set(existing.all())
    fresh = [row for row in candidates if (row[0], row[2], row[3]) not in claimed]
    if not fresh:
        return

    table = ExternalId.__table__
    columns = ("item_type", "item_id", "source", "external_id")
    temp_name = staging.add(table, columns, fresh)
    await staging.flush()
    await _insert_from_temp(
        session,
        table,
        columns,
        temp_name,
        conflict=(
            "ON CONFLICT ON CONSTRAINT uq_item_source "
            'DO UPDATE SET "external_id" = excluded."external_id"'
        ),
    )


async def _resolve_people(
    session: AsyncSession,
    staging: _Staging,
    people: list[BulkPerson],
    now: datetime,
) -> dict[tuple[str, str], int]:
    """Resolve every person of the batch to a ``people.id``.

    Acceptance #2: **one**
    ``SELECT ... WHERE (item_type, source, external_id) IN (...)``
    for the whole batch, instead of the ``get_person_id_by_external`` +
    ``get_person_by_id`` pair the per-item route issues per credit.  The
    people that query does not find are inserted with a single
    ``INSERT ... SELECT ... ON CONFLICT (uq_people_slug) DO UPDATE``, which
    also covers the case of two different external ids slugifying to the same
    name (the existing row wins, same as ``upsert_person``).
    """
    if not people:
        return {}
    keys = sorted({("PERSON", person.source, person.external_id) for person in people})
    found = await session.execute(
        select(ExternalId.source, ExternalId.external_id, ExternalId.item_id).where(
            tuple_(ExternalId.item_type, ExternalId.source, ExternalId.external_id).in_(keys),
        )
    )
    resolved: dict[tuple[str, str], int] = {
        (source, external_id): person_id for source, external_id, person_id in found.all()
    }

    unknown = [p for p in people if (p.source, p.external_id) not in resolved]
    if not unknown:
        return resolved

    table = Person.__table__
    columns = ("name", "slug", "profile_url", "last_synced_at")
    records: list[tuple] = []
    slug_of_key: dict[tuple[str, str], str] = {}
    seen_slugs: set[str] = set()
    for person in unknown:
        data = {
            "name": person.name,
            "slug": person.slug,
            "profile_url": person.profile_url,
            "last_synced_at": now,
        }
        try:
            record = _build_record(table, columns, data)
        except RowRejected as exc:
            logger.warning("bulk_load: dropping person %r — %s", person.slug, exc)
            continue
        slug_of_key[(person.source, person.external_id)] = person.slug
        if person.slug in seen_slugs:
            continue
        seen_slugs.add(person.slug)
        records.append(record)

    if not records:
        return resolved

    temp_name = staging.add(table, columns, records)
    await staging.flush()
    returned = await _insert_from_temp(
        session,
        table,
        columns,
        temp_name,
        conflict=(
            "ON CONFLICT ON CONSTRAINT uq_people_slug DO UPDATE SET "
            '"name" = excluded."name", "profile_url" = excluded."profile_url", '
            '"last_synced_at" = excluded."last_synced_at", "updated_at" = now()'
        ),
        returning=("id", "slug"),
    )
    id_by_slug = {slug: person_id for person_id, slug in returned}
    for key, slug in slug_of_key.items():
        person_id = id_by_slug.get(slug)
        if person_id is not None:
            resolved[key] = person_id

    await _upsert_external_ids(
        session,
        staging,
        [("PERSON", resolved[key], key[0], key[1]) for key in slug_of_key if key in resolved],
    )
    return resolved


# ── Entry point ──────────────────────────────────────────────────────────────


async def bulk_load_items(
    session: AsyncSession, spec: BulkLoadSpec, items: Sequence[BulkItem]
) -> BulkLoadResult:
    """Write a whole batch of items (+ genres, external ids, people, credits).

    Does **not** commit: the caller owns the transaction, so a failure can be
    rolled back and retried through the per-item route.  Invalid rows are
    dropped and counted (see the module docstring).
    """
    outcome = BulkLoadResult()
    if not items:
        return outcome

    table = spec.table
    relation_keys = spec.relation_keys
    now = datetime.now(UTC)

    # Column set = the union of the payload keys, minus the relation keys.
    # Every item of a slice comes from the same ``*_to_dict`` mapper so the
    # set is uniform in practice; a key an item lacks is written as NULL,
    # which the NOT NULL validation below turns into a rejection.
    columns: list[str] = []
    for item in items:
        for key in item.data:
            if key not in relation_keys and key not in columns:
                columns.append(key)
    for name in _defaulted_columns(table):
        if name not in columns:
            columns.append(name)
    if "slug" not in columns:
        raise ValueError(f"bulk_load_items: {spec.item_type} payload has no slug")

    valid: list[BulkItem] = []
    records: list[tuple] = []
    by_slug: dict[str, int] = {}
    for item in items:
        slug = item.data.get("slug")
        try:
            record = _build_record(table, columns, item.data)
        except RowRejected as exc:
            logger.warning("bulk_load: dropping %s row slug=%r — %s", spec.item_type, slug, exc)
            outcome.rejected += 1
            continue
        if slug in by_slug:
            # Same natural key twice in one batch: ON CONFLICT DO UPDATE
            # cannot touch a row twice, and a sequential run would leave the
            # last write standing, so replace instead of appending.
            position = by_slug[slug]
            valid[position] = item
            records[position] = record
            continue
        by_slug[slug] = len(valid)
        valid.append(item)
        records.append(record)

    if not records:
        return outcome

    staging = _Staging(session)
    temp_name = staging.add(table, columns, records)
    await staging.flush()
    returned = await _insert_from_temp(
        session,
        table,
        columns,
        temp_name,
        conflict=(f'ON CONFLICT ("slug") DO UPDATE SET {_locked_aware_update(table, columns)}'),
        returning=("id", "slug", "locked_fields") if "locked_fields" in table.c else ("id", "slug"),
    )
    ids_by_slug: dict[str, int] = {}
    locks_by_slug: dict[str, list[str]] = {}
    for row in returned:
        ids_by_slug[row[1]] = row[0]
        locks_by_slug[row[1]] = list(row[2]) if len(row) > 2 and row[2] else []
    if len(ids_by_slug) != len(records):
        # ON CONFLICT DO UPDATE ... RETURNING gives back one row per record,
        # inserted or updated, and the records were de-duplicated by slug
        # above — so anything else means the write did not land as intended.
        # Raising hands the batch to the caller's per-item fallback instead of
        # silently reporting a partial slice as done (feature 84, D2 level 2).
        raise BulkLoadError(
            f"{spec.item_type}: batch INSERT returned {len(ids_by_slug)} rows "
            f"for {len(records)} records"
        )
    outcome.written = len(ids_by_slug)

    # ── Lookup relations (genres, platforms) ────────────────────────────────
    for lookup in spec.lookups:
        rows: list[dict[str, Any]] = []
        touched_ids: list[int] = []
        pairs_source: list[tuple[int, str]] = []
        for item in valid:
            slug = item.data["slug"]
            item_id = ids_by_slug.get(slug)
            if item_id is None:
                continue
            entries = item.data.get(lookup.data_key) or []
            if not entries:
                continue
            if lookup.lockable and lookup.data_key in locks_by_slug.get(slug, []):
                continue
            touched_ids.append(item_id)
            for entry in entries:
                rows.append(dict(entry))
                pairs_source.append((item_id, entry["slug"]))
        if not touched_ids:
            continue
        id_by_slug = await _load_lookup_rows(
            session, staging, lookup.lookup_table, lookup.lookup_columns, rows
        )
        pairs = []
        unresolved: set[str] = set()
        for item_id, lookup_slug in pairs_source:
            lookup_id = id_by_slug.get(lookup_slug)
            if lookup_id is None:
                # Should not happen: the upsert above returns a row for every
                # slug it staged, new or pre-existing.  If it ever does, the
                # item loses that entry — say so instead of degrading in
                # silence (this is the one spot where the batch route could
                # quietly write less than it was asked to).
                unresolved.add(lookup_slug)
                continue
            pairs.append((item_id, lookup_id))
        if unresolved:
            logger.warning(
                "bulk_load: %s — %d %s slug(s) did not resolve to an id, "
                "affected items lose those entries: %s",
                spec.item_type,
                len(unresolved),
                lookup.lookup_table.name,
                sorted(unresolved),
            )
        await _replace_join_rows(session, staging, lookup, touched_ids, pairs)

    # ── Item external ids ───────────────────────────────────────────────────
    await _upsert_external_ids(
        session,
        staging,
        [
            (spec.item_type, ids_by_slug[item.data["slug"]], spec.source, item.external_id)
            for item in valid
            if item.external_id and item.data["slug"] in ids_by_slug
        ],
    )

    # ── Entity credits (game companies) ─────────────────────────────────────
    for entity in spec.entity_credits:
        await _load_entity_credits(session, staging, spec, entity, valid, ids_by_slug)

    # ── People + credits ────────────────────────────────────────────────────
    await _load_people_credits(
        session,
        staging,
        spec.item_type,
        [
            (ids_by_slug[item.data["slug"]], item.people)
            for item in valid
            if item.people and item.data["slug"] in ids_by_slug
        ],
        outcome,
        now,
    )

    return outcome


async def _load_people_credits(
    session: AsyncSession,
    staging: _Staging,
    item_type: str,
    entries: Sequence[tuple[int, Sequence[BulkPerson]]],
    outcome: BulkLoadResult,
    now: datetime,
) -> None:
    """Write the people + credits of a whole batch, item ids already known.

    Split out of ``bulk_load_items`` for feature 85: the targeted credits
    backfill has the item rows already persisted and only needs this half of
    the batch route, so the two callers must not drift apart.  Incomplete
    person payloads and credits whose person could not be resolved are
    dropped and counted in ``outcome.people_rejected`` — same contract the
    per-item route has always had.  Does not commit.
    """
    people: list[BulkPerson] = []
    credit_rows: list[tuple[int, BulkPerson]] = []
    for item_id, persons in entries:
        for person in persons:
            if not person.external_id or not person.name or not person.slug or not person.role:
                logger.warning(
                    "bulk_load: dropping credit on %s id=%s — incomplete person payload",
                    item_type,
                    item_id,
                )
                outcome.people_rejected += 1
                continue
            people.append(person)
            credit_rows.append((item_id, person))

    if not credit_rows:
        return

    resolved = await _resolve_people(session, staging, people, now)
    credit_table = Credit.__table__
    credit_columns = (
        "item_type",
        "item_id",
        "person_id",
        "role",
        "character_name",
        "billing_order",
    )
    deduped: dict[tuple[str, int, int, str], tuple] = {}
    for item_id, person in credit_rows:
        person_id = resolved.get((person.source, person.external_id))
        if person_id is None:
            outcome.people_rejected += 1
            continue
        data = {
            "item_type": item_type,
            "item_id": item_id,
            "person_id": person_id,
            "role": person.role,
            "character_name": person.character_name,
            "billing_order": person.billing_order,
        }
        try:
            record = _build_record(credit_table, credit_columns, data)
        except RowRejected as exc:
            logger.warning("bulk_load: dropping credit %r — %s", data, exc)
            outcome.people_rejected += 1
            continue
        deduped[(item_type, item_id, person_id, person.role)] = record
    if not deduped:
        return

    credit_records = list(deduped.values())
    temp_name = staging.add(credit_table, credit_columns, credit_records)
    await staging.flush()
    await _insert_from_temp(
        session,
        credit_table,
        credit_columns,
        temp_name,
        conflict=(
            "ON CONFLICT ON CONSTRAINT uq_credit DO UPDATE SET "
            '"character_name" = excluded."character_name", '
            '"billing_order" = excluded."billing_order"'
        ),
    )
    outcome.people_written += len(credit_records)


async def bulk_load_credits(
    session: AsyncSession,
    item_type: str,
    entries: Sequence[tuple[int, Sequence[BulkPerson]]],
) -> BulkLoadResult:
    """Write only people + credits for items that already exist (feature 85).

    The targeted credits backfill knows the ``item_id`` of every row it works
    on (it got them from the local gap query) and must **not** re-write the
    item itself — the row is already there, only its credits are missing.
    This is ``bulk_load_items`` minus the item/lookup/external-id stages:
    same COPY-into-temp-table plus ``INSERT ... SELECT ... ON CONFLICT``
    route, same single query resolving every person of the batch.

    Does not commit: the caller owns the transaction so a failure can be
    rolled back and retried through the per-item route.
    """
    outcome = BulkLoadResult()
    if not entries:
        return outcome
    await _load_people_credits(
        session, _Staging(session), item_type, entries, outcome, datetime.now(UTC)
    )
    return outcome


async def _load_entity_credits(
    session: AsyncSession,
    staging: _Staging,
    spec: BulkLoadSpec,
    entity: EntityCreditSpec,
    items: Sequence[BulkItem],
    ids_by_slug: dict[str, int],
) -> None:
    """Batch version of the game companies -> company_credits write."""
    entity_rows: list[dict[str, Any]] = []
    credits: list[tuple[int, str, str]] = []
    for item in items:
        item_id = ids_by_slug.get(item.data["slug"])
        if item_id is None:
            continue
        for entry in item.data.get(entity.data_key) or []:
            row = dict(entry)
            row.pop("role", None)
            for column_name, factory in entity.entity_defaults:
                row.setdefault(column_name, factory())
            entity_rows.append(row)
            credits.append((item_id, entry["slug"], entry["role"]))
    if not credits:
        return

    id_by_slug = await _load_lookup_rows(
        session, staging, entity.entity_table, entity.entity_columns, entity_rows
    )
    columns = ("item_type", "item_id", entity.entity_fk, "role")
    deduped: dict[tuple, tuple] = {}
    for item_id, entity_slug, role in credits:
        entity_id = id_by_slug.get(entity_slug)
        if entity_id is None:
            continue
        deduped[(spec.item_type, item_id, entity_id, role)] = (
            spec.item_type,
            item_id,
            entity_id,
            role,
        )
    if not deduped:
        return
    temp_name = staging.add(entity.credit_table, columns, list(deduped.values()))
    await staging.flush()
    await _insert_from_temp(
        session,
        entity.credit_table,
        columns,
        temp_name,
        conflict=f"ON CONFLICT ON CONSTRAINT {entity.constraint} DO NOTHING",
    )


async def rollback_quietly(session: AsyncSession, context: str) -> None:
    """Roll back after a failure so the shared session stays usable.

    Without this an aborted transaction poisons the session: every later
    statement fails with InFailedSQLTransactionError and even the cursor
    commit is lost.  ``expunge_all`` drops the identity map that
    ``rollback()`` just expired, so the next write does not touch an expired
    attribute (that would fire a sync lazy-load inside the async session).
    """
    try:
        await session.rollback()
        session.expunge_all()
    except Exception:
        logger.exception("%s: rollback after failure failed", context)
