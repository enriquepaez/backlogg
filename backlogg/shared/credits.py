"""Credits shared across every catalog domain.

Holds the role vocabulary of the polymorphic ``credits`` table, the shape of
the denormalised cast in ``item_cast``, and the reads that are not owned by
any single vertical slice.

The TMDB crew allowlists below are the single source of truth for which crew
jobs become credits in movies **and** series: the mapping lives here, not as
loose string literals inside each ``service.py`` (feature 74).

Since feature 89 the two halves of what used to be one table live apart:
``credits`` is the **navigation graph** (``GRAPH_ROLES``) and ``item_cast``
holds the **cast of a detail page** (``CAST_ROLE``).  The split is invisible
above this module: ``get_credits_for_item`` merges both back into the same
``CreditOut`` list, in the same order, that the detail endpoints have always
returned.  See ``docs/schema.md``.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.shared.models import Credit, ItemCast, Person
from backlogg.shared.schemas import CreditOut
from backlogg.shared.slugs import slugify

# ── Role vocabulary ──────────────────────────────────────────────────────────

#: Roles that mean "wrote the work itself", across every ``item_type``:
#: ``AUTHOR`` on books, ``SOURCE_AUTHOR`` on the film/series adapted from a
#: prior work.  This is the cross-type authorship class of layer 0 in
#: ``docs/recommendations-plan.md``.  ``WRITER`` is deliberately **not** here:
#: a screenwriter did not write the source work, and the role carries zero
#: weight as a recommendation signal.
AUTHORSHIP_ROLES: tuple[str, ...] = ("AUTHOR", "SOURCE_AUTHOR")

#: The one role that is **detail-page data**, not graph: it never earns a
#: ``people`` row, a ``external_ids`` row or a ``credits`` row.  It is written
#: to ``item_cast`` instead (feature 89).  A single name so that the two write
#: frontiers — the per-item route and ``shared/bulk_load.py`` — split on the
#: same rule and cannot drift.
CAST_ROLE: str = "ACTOR"

#: Everything that *does* build the navigation graph and therefore keeps its
#: relational row: "other works by this person" plus the cross-type authorship
#: bridge of feature 74.
#:
#: Nothing branches on this tuple — the write paths branch on ``CAST_ROLE``,
#: of which this is the complement, because "is it cast?" is the question they
#: actually ask and a complement cannot fall out of sync with itself.  This is
#: executable documentation: the enumeration of what survives in ``credits``
#: after feature 89, in one place, next to the constant that decides it.
GRAPH_ROLES: tuple[str, ...] = ("DIRECTOR", "CREATOR", "WRITER", "AUTHOR", "SOURCE_AUTHOR")

# ── TMDB crew job allowlists (feature 74) ────────────────────────────────────
#
# Ingestion filters the crew by *job*, never by ``department == "Writing"``:
# TMDB tells the author of the source work apart from the screenwriter by job,
# and the same department also carries animation storyboard jobs (``Story
# Artist``, ``Head of Story``, ``Story Supervisor``) that must never become
# credits.  Jobs absent from both lists are simply not persisted.
# See docs/schema.md § "`SOURCE_AUTHOR` vs `WRITER` (movies and series)".

#: Author of the **source work** — the book -> film/series cross-type bridge.
#: ``Story``, ``Screenstory`` and ``Original Story`` are excluded on purpose: in
#: TMDB all three mean "screen story", original material written for the screen,
#: not a prior work (*Inside Out* credits Pete Docter with ``Original Story``).
TMDB_SOURCE_AUTHOR_JOBS: tuple[str, ...] = (
    "Novel",
    "Book",
    "Short Story",
    "Comic Book",
    "Graphic Novel",
    "Theatre Play",
    "Characters",
)

#: Screenwriter.  Detail-page data only (the Credits section of
#: ``docs/detail-page-layout.md``), never a recommendation signal.
TMDB_WRITER_JOBS: tuple[str, ...] = (
    "Screenplay",
    "Writer",
    "Teleplay",
    "Adaptation",
    "Dialogue",
)

_WRITING_CREW_JOB_ROLES: dict[str, str] = {
    **{job: "SOURCE_AUTHOR" for job in TMDB_SOURCE_AUTHOR_JOBS},
    **{job: "WRITER" for job in TMDB_WRITER_JOBS},
}

#: Movie crew: the director plus the writing jobs.
MOVIE_CREW_JOB_ROLES: dict[str, str] = {"Director": "DIRECTOR", **_WRITING_CREW_JOB_ROLES}

#: Series crew: the writing jobs only.  ``CREATOR`` comes from the detail
#: payload's ``created_by``, and ``/tv/{id}/credits`` carries no meaningful
#: series-level director.
SERIES_CREW_JOB_ROLES: dict[str, str] = dict(_WRITING_CREW_JOB_ROLES)


def select_crew_credits(
    crew: Sequence[dict] | None,
    job_roles: Mapping[str, str],
) -> list[tuple[dict, str]]:
    """Pair each allowlisted crew member with the role it maps to.

    Returns ``(member, role)`` in payload order, keeping at most one entry per
    ``(person id, role)``: TMDB routinely credits the same person with two jobs
    that fold into the same role (``Screenplay`` *and* ``Writer`` is common),
    and both the per-item and the bulk write paths would otherwise be handed a
    duplicate of the primary key of ``credits``.
    """
    pairs: list[tuple[dict, str]] = []
    seen: set[tuple[object, str]] = set()
    for member in crew or []:
        role = job_roles.get(member.get("job"))
        if role is None:
            continue
        key = (member.get("id"), role)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((member, role))
    return pairs


# ── The cast payload (feature 89) ────────────────────────────────────────────
#
# One-character keys, because they are repeated once per actor across the
# whole catalog (~518.000 times in production) and payload size is the reason
# this table exists.  Named here so that no other module ever spells them out.

_CAST_NAME_KEY = "n"
_CAST_CHARACTER_KEY = "c"
_CAST_ORDER_KEY = "o"


def build_cast_payload(entries: Iterable[tuple[str, str | None, int | None]]) -> list[dict]:
    """Build the ``item_cast.payload`` array from ``(name, character, order)``.

    Sorted by billing order ascending with the unknown ones last — the array is
    stored already ordered so the read path never has to sort — and **never
    truncated**: the detail page keeps showing the full cast.  Entries with no
    name are dropped: they would render as a blank line and carry nothing.
    """
    rows = [entry for entry in entries if entry[0]]
    rows.sort(key=lambda entry: (entry[2] is None, entry[2] if entry[2] is not None else 0))
    payload: list[dict] = []
    for name, character, order in rows:
        row: dict[str, Any] = {_CAST_NAME_KEY: name}
        if character:
            row[_CAST_CHARACTER_KEY] = character
        if order is not None:
            row[_CAST_ORDER_KEY] = order
        payload.append(row)
    return payload


def cast_payload_to_credits(payload: Sequence[dict] | None) -> list[CreditOut]:
    """Render a stored cast payload as ``CreditOut`` rows, in stored order.

    ``person_slug`` is derived from the name rather than stored: a cast-only
    person has no ``people`` row any more, so the slug is a label (it is the
    React key of ``apps/web``'s ``ItemCredits``), not a link that resolves —
    ``GET /people/{slug}`` answers 404 for them by design (``docs/api.md``).
    Storing it would add ~18 B per actor to buy nothing.  It can come out
    **empty** for a name written entirely in a non-Latin script (issue #18),
    which is harmless precisely because nothing resolves it: the React key
    also carries the index, and the name itself is intact in ``person_name``.  ``profile_url`` is
    ``None`` for the same reason: it would roughly double the payload — the
    one number this whole feature is trying to bring down — and no consumer
    reads it.
    """
    return [
        CreditOut(
            person_name=entry[_CAST_NAME_KEY],
            person_slug=slugify(entry[_CAST_NAME_KEY]),
            profile_url=None,
            role=CAST_ROLE,
            character_name=entry.get(_CAST_CHARACTER_KEY),
            billing_order=entry.get(_CAST_ORDER_KEY),
        )
        for entry in payload or []
        if entry.get(_CAST_NAME_KEY)
    ]


# ── Writes ───────────────────────────────────────────────────────────────────


async def upsert_item_cast(
    db: AsyncSession,
    item_type: str,
    rows: Sequence[tuple[int, list[dict]]],
) -> int:
    """Replace the stored cast of every ``(item_id, payload)`` in ``rows``.

    One statement for the whole batch, whatever its size: the payload is a
    single column, so a multi-row ``VALUES`` costs three bind parameters per
    item and one round trip — no need for the COPY staging that
    ``shared/bulk_load.py`` uses for the wide tables.  Rewrites the array
    wholesale rather than merging: the cast of an item is one indivisible fact
    coming from one payload, and a partial refresh would leave actors from a
    previous ingestion mixed in.  Does not commit.
    """
    if not rows:
        return 0
    insert = pg_insert(ItemCast).values(
        [
            {"item_type": item_type, "item_id": item_id, "payload": payload}
            for item_id, payload in rows
        ]
    )
    stmt = insert.on_conflict_do_update(
        index_elements=[ItemCast.item_type, ItemCast.item_id],
        set_={"payload": insert.excluded.payload},
    )
    await db.execute(stmt)
    await db.flush()
    return len(rows)


# ── Reads ────────────────────────────────────────────────────────────────────


async def get_credits_for_item(db: AsyncSession, item_type: str, item_id: int) -> list[CreditOut]:
    """Return every credit of an item: the cast first, then the crew.

    Since feature 89 this merges the two halves of the old ``credits`` table —
    the cast from ``item_cast`` and the graph roles from ``credits`` — back
    into the shape and the order the detail endpoints have always returned.
    That order is the one the previous single query produced with ``ORDER BY
    billing_order ASC NULLS LAST``: only cast rows ever carried a
    ``billing_order``, so they came first, in billing order, and every crew
    row landed after them.  ``apps/web`` renders this list verbatim.

    The crew tie-break is ``(created_at, person_id)``: crew rows have no
    billing order to sort by and Postgres would otherwise return them in
    physical order, which changes under the feet of any row update.
    """
    cast_row = await db.execute(
        select(ItemCast.payload).where(ItemCast.item_type == item_type, ItemCast.item_id == item_id)
    )
    credits_out = cast_payload_to_credits(cast_row.scalar_one_or_none())

    result = await db.execute(
        select(Credit, Person)
        .join(Person, Credit.person_id == Person.id)
        .where(Credit.item_type == item_type, Credit.item_id == item_id)
        .order_by(Credit.created_at.asc(), Credit.person_id.asc())
    )
    credits_out.extend(
        CreditOut(
            person_name=person.name,
            person_slug=person.slug,
            profile_url=person.profile_url,
            role=credit.role,
            character_name=None,
            billing_order=None,
        )
        for credit, person in result.all()
    )
    return credits_out
