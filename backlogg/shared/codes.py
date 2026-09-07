"""Compact on-disk codes for the polymorphic ``item_type`` and ``role`` columns.

Feature 89.  ``credits`` used to store ``item_type`` as ``VARCHAR(20)`` and
``role`` as ``VARCHAR(50)`` — the literal strings ``'MOVIE'`` and ``'ACTOR'``
repeated on every one of the 710.772 rows of production *and* on every one of
the four columns of ``uq_credit``, which is why that single index weighed
35 MB.  Both columns are now ``smallint``.

**Why ``smallint`` and not a native PostgreSQL ``ENUM``** — the three reasons,
in order of weight:

1. **Size.**  This feature exists because the database does not fit in Neon's
   512 MB.  A native enum value is an ``oid``: **4 bytes**.  A ``smallint`` is
   **2**.  With two such columns on 710k rows plus their copies inside three
   indexes, the enum costs several MB more for the exact same vocabulary.
2. **Adding a value is DDL.**  ``ALTER TYPE ... ADD VALUE`` is a schema
   migration, so a new role (or a fifth content type) would need one *and* a
   deploy window; here it is a line in the dict below.
3. **``item_type`` is not local to this table.**  It also lives in
   ``external_ids``, ``catalog_search``, ``seed_targets``, ``sync_cursors``,
   ``activity_events``, ``library_entries``, ``notifications`` and
   ``company_credits`` — all of them as text.  A native enum on ``credits``
   only would make every comparison against those tables a cross-type one
   needing an explicit cast, and converting *all* of them is a much larger
   change than feature 89 is allowed to be.

**Why the application never sees the numbers.**  The mapping is applied by the
two ``TypeDecorator``s below, at the persistence boundary and nowhere else, so
``Credit.item_type == "MOVIE"`` and ``credit.role == "AUTHOR"`` keep working
verbatim across the whole codebase.  That is deliberate: the alternative —
sprinkling ``ITEM_TYPE_CODES["MOVIE"]`` through every service and repository —
is precisely the "magic numbers spread around" this module exists to prevent,
and it would have made the diff of a storage change reach into business logic.

Codes are **append-only and never reused**: they are written on disk.  Adding
a value means taking the next free number; changing one means a data
migration.
"""

from typing import Any

from sqlalchemy import SmallInteger
from sqlalchemy.types import TypeDecorator

__all__ = [
    "CREDIT_ROLE_CODES",
    "ITEM_TYPE_CODES",
    "CreditRoleCode",
    "ItemTypeCode",
]

#: The polymorphic content-type vocabulary, as stored by the narrow columns.
#: ``PERSON`` is not a catalog type but travels in the same vocabulary because
#: ``external_ids`` uses it; it is listed here so the two never drift.
ITEM_TYPE_CODES: dict[str, int] = {
    "MOVIE": 1,
    "SERIES": 2,
    "BOOK": 3,
    "GAME": 4,
    "PERSON": 5,
}

#: The credit role vocabulary.  ``ACTOR`` is kept even though feature 89 moved
#: the cast out of ``credits`` and into ``item_cast``: the downgrade of
#: migration ``0037`` rebuilds ``ACTOR`` rows, and the merged detail read
#: labels every cast entry with it.
CREDIT_ROLE_CODES: dict[str, int] = {
    "ACTOR": 1,
    "DIRECTOR": 2,
    "WRITER": 3,
    "AUTHOR": 4,
    "SOURCE_AUTHOR": 5,
    "CREATOR": 6,
}

_ITEM_TYPE_NAMES: dict[int, str] = {code: name for name, code in ITEM_TYPE_CODES.items()}
_CREDIT_ROLE_NAMES: dict[int, str] = {code: name for name, code in CREDIT_ROLE_CODES.items()}


class _CodedString(TypeDecorator[str]):
    """A ``smallint`` column the application reads and writes as a string.

    Unknown values raise instead of being coerced or dropped: a typo in a role
    name is a bug, and silently writing ``NULL`` (or a stray number) into a
    column that indexes the whole credits graph would be found months later.
    """

    impl = SmallInteger
    cache_ok = True

    codes: dict[str, int] = {}
    names: dict[int, str] = {}
    label = "value"

    def process_bind_param(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return self.codes[value]
            except KeyError:
                raise ValueError(
                    f"unknown {self.label}: {value!r} — add it to "
                    f"backlogg/shared/codes.py before persisting it"
                ) from None
        raise TypeError(f"{self.label} must be a str, got {type(value).__name__}")

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        try:
            return self.names[value]
        except KeyError:  # pragma: no cover - only reachable on corrupt data
            raise ValueError(f"unknown {self.label} code: {value!r}") from None


class ItemTypeCode(_CodedString):
    """``item_type`` stored as ``smallint`` (see ``ITEM_TYPE_CODES``)."""

    cache_ok = True
    codes = ITEM_TYPE_CODES
    names = _ITEM_TYPE_NAMES
    label = "item_type"


class CreditRoleCode(_CodedString):
    """``credits.role`` stored as ``smallint`` (see ``CREDIT_ROLE_CODES``)."""

    cache_ok = True
    codes = CREDIT_ROLE_CODES
    names = _CREDIT_ROLE_NAMES
    label = "credit role"
