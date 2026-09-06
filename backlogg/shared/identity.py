"""Item identity: the **external id owns the row**, the slug only names it.

Issue #23.  Every catalog write path used to resolve an item by its slug —
``INSERT ... ON CONFLICT ("slug") DO UPDATE`` — while ``external_ids`` resolved
it by ``(item_type, source, external_id)``.  Those two identities agree right
up until the source renames something, and then they disagree forever:

    TMDB 284753  "Operation Safed Sagar: The Highest Air Force Mission"
                 -> series.id=4,  slug operation-safed-sagar-...-2025, linked
    TMDB 284753  "... The Untold Story of the Kargil War"   (same id, new title)
                 -> new slug, no row matches, a SECOND row is inserted
                 -> series.id=1265, and it can never be linked: the triple is
                    already claimed by id 4, so the link pre-check skips it

The result is a permanent duplicate plus a frozen item: unreachable by external
id, invisible to the refresh rotation and to ``get_credit_gaps``.  Measured for
real on the dev database (issue #22's QA: a 5-item refresh slice produced
``skipped_links=1``, and that was this).

The rule this module implements
-------------------------------

When an item arrives with an external identity, **that identity decides which
row it is**.  Before the slug-keyed upsert runs, the row already linked to
``(item_type, source, external_id)`` is looked up and its slug is *realigned*
to the one the payload proposes, so the ``ON CONFLICT ("slug")`` lands on that
same row and updates it.  A rename therefore updates one row (id preserved,
slug refreshed) instead of forking a second one.

Slugs are consequently **no longer immutable** for linked items.  That is the
product decision behind this issue, and it is what makes the catalog converge:
a stable-looking URL that points at a duplicate nobody refreshes is worth less
than a URL that follows the item.

When the realignment does **not** happen
----------------------------------------

Three cases keep the stored slug and only redirect the write onto the right
row (never a second one, never an ``IntegrityError``):

1. **The new slug is already another row's slug.**  ``uq_*_slug`` is a real
   constraint; renaming into it would raise, and stealing the name would leave
   *that* item mis-slugged.  Two distinct source items whose title and year
   fold to the same value is a known, separate problem (issue #24 territory);
   this module refuses to make it worse.
2. **Two items of the same batch propose the same new slug.**  Nobody renames:
   picking a winner by list order would make the outcome depend on the fetch
   order of a slice.
3. **``title`` is admin-locked** (feature 49).  The displayed title is the
   admin's, so the slug must keep matching it and not the source's.

All three are logged: the item stays reachable under its old slug, which is a
cosmetic loss, whereas a duplicate is a permanent data loss.

A collision detected here is also *not* the same thing as the race of two
writers renaming concurrently.  The check and the ``UPDATE`` are not atomic, so
the ``UPDATE`` runs inside a ``SAVEPOINT``: if somebody took the slug in
between, the savepoint rolls back, every rename of the call keeps its old slug
and the caller's upsert still lands on the right row.  A rename losing a race
must never turn an on-demand request into a 500.
"""

import logging
from collections import Counter
from collections.abc import Mapping

from sqlalchemy import Table, bindparam, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.shared.external_ids import ExternalId

logger = logging.getLogger(__name__)

__all__ = ["align_slugs_to_external_ids", "resolve_item_slug"]

# The admin lock (feature 49) that freezes the slug with it: the slug is
# derived from the title, so a locked title must not be renamed by the source.
_TITLE_LOCK = "title"


async def _slug_owners(session: AsyncSession, table: Table, slugs: list[str]) -> dict[str, int]:
    """``slug -> id`` for the slugs a rename wants to move into.

    Its own function so the race it cannot cover has a seam: between this read
    and the ``UPDATE`` another writer may take the slug, and the test suite
    reproduces exactly that by making this return an empty mapping.
    """
    if not slugs:
        return {}
    result = await session.execute(select(table.c.slug, table.c.id).where(table.c.slug.in_(slugs)))
    return {slug: row_id for slug, row_id in result.all()}


async def align_slugs_to_external_ids(
    session: AsyncSession,
    *,
    item_type: str,
    table: Table,
    source: str,
    proposed: Mapping[str, str],
) -> dict[str, str]:
    """Resolve ``external_id -> slug to upsert with`` for a whole batch.

    ``proposed`` maps each external id to the slug its payload would use.  The
    returned dict only contains the external ids that are **already linked** to
    a live row: for those the caller must write with the returned slug, which
    is either the proposed one (the row was renamed to it right here) or the
    row's current one (a case from the module docstring).  External ids absent
    from the result are new to the catalog and keep their proposed slug.

    Costs one ``SELECT`` per call, plus a second ``SELECT`` and one ``UPDATE``
    only when something actually got renamed — i.e. nothing at all on a batch
    of new items, which is the seeding case.  Per batch, never per item: the
    batch route's whole reason to exist is its round-trip budget
    (``backlogg.shared.bulk_load``).

    Does not commit; the caller owns the transaction.
    """
    wanted = {external_id: slug for external_id, slug in proposed.items() if external_id and slug}
    if not wanted:
        return {}

    has_locks = "locked_fields" in table.c
    columns = [ExternalId.external_id, ExternalId.item_id, table.c.slug]
    if has_locks:
        columns.append(table.c.locked_fields)
    linked = await session.execute(
        select(*columns)
        .select_from(ExternalId)
        # No FK backs ``external_ids.item_id`` (docs/conventions.md), so the
        # join is spelled out — and being an INNER join it also drops rows
        # pointing at an item that no longer exists: a dangling link owns
        # nothing and must not decide any identity.
        .join(table, table.c.id == ExternalId.item_id)
        .where(
            ExternalId.item_type == item_type,
            ExternalId.source == source,
            ExternalId.external_id.in_(list(wanted)),
        )
    )

    resolved: dict[str, str] = {}
    renames: list[tuple[str, int, str, str]] = []
    for row in linked.all():
        external_id, item_id, current = row[0], row[1], row[2]
        locked = tuple(row[3] or ()) if has_locks else ()
        target = wanted[external_id]
        if current == target:
            resolved[external_id] = current
            continue
        if _TITLE_LOCK in locked:
            logger.info(
                "identity: %s (%s, %s) keeps slug %r — its title is admin-locked, "
                "so the source's rename to %r is not applied",
                item_type,
                source,
                external_id,
                current,
                target,
            )
            resolved[external_id] = current
            continue
        renames.append((external_id, item_id, current, target))

    if not renames:
        return resolved

    # Two items of this call proposing one slug: neither may take it.
    contested = {slug for slug, count in Counter(wanted.values()).items() if count > 1}
    owners = await _slug_owners(session, table, [target for _, _, _, target in renames])

    safe: list[tuple[str, int, str, str]] = []
    for external_id, item_id, current, target in renames:
        owner = owners.get(target)
        if owner is not None and owner != item_id:
            logger.warning(
                "identity: %s (%s, %s) keeps slug %r — its new slug %r already belongs "
                "to item_id=%s; the item is updated in place, only its URL stays stale",
                item_type,
                source,
                external_id,
                current,
                target,
                owner,
            )
            resolved[external_id] = current
            continue
        if target in contested:
            logger.warning(
                "identity: %s (%s, %s) keeps slug %r — more than one item of this batch "
                "proposes the slug %r, and picking one would depend on fetch order",
                item_type,
                source,
                external_id,
                current,
                target,
            )
            resolved[external_id] = current
            continue
        safe.append((external_id, item_id, current, target))

    if not safe:
        return resolved

    try:
        async with session.begin_nested():
            await session.execute(
                update(table)
                .where(table.c.id == bindparam("b_id"))
                .values(slug=bindparam("b_slug")),
                [{"b_id": item_id, "b_slug": target} for _, item_id, _, target in safe],
            )
    except IntegrityError:
        # Somebody claimed one of these slugs between the check and the write.
        # Everything in the savepoint is undone, so every row still holds its
        # old slug — report exactly that, and the upsert still finds its row.
        logger.warning(
            "identity: %s renames rolled back — a concurrent writer took one of the "
            "slugs %s; the items keep their current slug and are still updated in place",
            item_type,
            [target for _, _, _, target in safe],
        )
        for external_id, _, current, _ in safe:
            resolved[external_id] = current
        return resolved

    for external_id, item_id, current, target in safe:
        logger.info(
            "identity: %s (%s, %s) renamed at the source — item_id=%s slug %r -> %r",
            item_type,
            source,
            external_id,
            item_id,
            current,
            target,
        )
        resolved[external_id] = target
    return resolved


async def resolve_item_slug(
    session: AsyncSession,
    *,
    item_type: str,
    table: Table,
    source: str,
    external_id: str,
    proposed_slug: str,
) -> str:
    """Single-item form of :func:`align_slugs_to_external_ids`.

    Deliberately built on top of the batch function instead of duplicating the
    rule: the on-demand routes (``GET /movies/{slug}``, ``/similar``, the
    search fan-out, ``trending``) and the seeding batches must resolve identity
    identically, or the same TMDB id would mean two different rows depending on
    which door it came through — which is the bug this module exists to close.
    """
    aligned = await align_slugs_to_external_ids(
        session,
        item_type=item_type,
        table=table,
        source=source,
        proposed={external_id: proposed_slug},
    )
    return aligned.get(external_id, proposed_slug)
