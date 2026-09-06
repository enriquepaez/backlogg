"""Credits shared across every catalog domain.

Holds the role vocabulary of the polymorphic ``credits`` table (roles are free
text — ``role`` is a ``String(50)`` with no enum and no check constraint) and
the reads that are not owned by any single vertical slice.

The TMDB crew allowlists below are the single source of truth for which crew
jobs become credits in movies **and** series: the mapping lives here, not as
loose string literals inside each ``service.py`` (feature 74).
"""

from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.shared.models import Credit, Person
from backlogg.shared.schemas import CreditOut

# ── Role vocabulary ──────────────────────────────────────────────────────────

#: Roles that mean "wrote the work itself", across every ``item_type``:
#: ``AUTHOR`` on books, ``SOURCE_AUTHOR`` on the film/series adapted from a
#: prior work.  This is the cross-type authorship class of layer 0 in
#: ``docs/recommendations-plan.md``.  ``WRITER`` is deliberately **not** here:
#: a screenwriter did not write the source work, and the role carries zero
#: weight as a recommendation signal.
AUTHORSHIP_ROLES: tuple[str, ...] = ("AUTHOR", "SOURCE_AUTHOR")

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
    duplicate of the ``uq_credit`` tuple.
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


# ── Reads ────────────────────────────────────────────────────────────────────


async def get_credits_for_item(db: AsyncSession, item_type: str, item_id: int) -> list[CreditOut]:
    """Return credits for an item ordered by billing_order ascending.

    Credits without billing_order are placed last.
    """
    result = await db.execute(
        select(Credit, Person)
        .join(Person, Credit.person_id == Person.id)
        .where(Credit.item_type == item_type, Credit.item_id == item_id)
        .order_by(Credit.billing_order.asc().nulls_last())
    )
    rows = result.all()
    return [
        CreditOut(
            person_name=person.name,
            person_slug=person.slug,
            profile_url=person.profile_url,
            role=credit.role,
            character_name=credit.character_name,
            billing_order=credit.billing_order,
        )
        for credit, person in rows
    ]
