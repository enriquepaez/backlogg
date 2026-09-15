"""The ranker of ``docs/recommendations-plan.md`` § «El ranker» — pure functions.

Everything in this module is a **pure function over already-fetched
candidates**: no session, no query, no I/O.  That is deliberate and it is what
makes the two rules of feature 80 testable as rules rather than as end-to-end
behaviour — a cross-type quota that only shows up when the development catalog
happens to hold the right neighbours is a quota nobody can prove.

The DB half lives in ``similar.py`` (orchestration) and
``repository.py`` (queries, per ``docs/architecture.md`` principle 3).

Three things happen here, in this order:

1. **Diversification.**  Greedy re-rank with a multiplicative penalty every
   time a candidate repeats a *group* already taken — same creator, or same
   franchise.  "Ten results from the same saga are not ten recommendations."
2. **Cross-type quota.**  At least ``quota`` of the ``limit`` slots go to items
   of a different type from the anchor's.  Applied *after* diversification, on
   the diversified order, so the quota picks the best *diverse* neighbours of
   the other types rather than the raw cosine top.
3. **Truncation** to ``limit``, keeping the diversified order.

Why the quota exists at all: the plan says cosine on its own returns the
anchor's own type almost every time, because items of one type share vocabulary
("season", "player", "novel") and that vocabulary dominates the metric.  The
quota is the only reason a cross-media result reaches the user at all.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "Candidate",
    "SIMILAR_RESULT_LIMIT",
    "apply_cross_type_quota",
    "diversify",
    "franchise_key",
    "group_keys",
    "rank_similar",
]

#: How many results one ``/similar`` response carries.  Ten everywhere since
#: feature 16; the per-domain services used to each hold their own ``10``.
SIMILAR_RESULT_LIMIT = 10


@dataclass(frozen=True, slots=True)
class Candidate:
    """One neighbour, hydrated with everything the ranker and the response need.

    ``creator_ids`` is the diversification signal that comes from data rather
    than from the title: the ``people``/``credits`` graph restricted to the
    roles that mean "this person made it" (``AUTHOR`` on books, ``DIRECTOR`` on
    films, ``CREATOR`` on series).  Games contribute none — they carry no
    person credits at all (``docs/schema.md``) — which is exactly why the
    title-derived ``franchise_key`` exists next to it.
    """

    item_type: str
    item_id: int
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    rating_internal: float | None
    score: float
    creator_ids: frozenset[int] = field(default_factory=frozenset)


# A subtitle separator: "The Lord of the Rings: The Return of the King",
# "Mass Effect - Andromeda", "Final Fantasy VII – Remake".
_SUBTITLE_SPLIT = re.compile(r"\s*[:–—]\s+|\s+[-–—]\s+")
# A trailing sequel marker: "Mass Effect 2", "Rocky IV", "Part 3".
_SEQUEL_TAIL = re.compile(
    r"\s+(?:part\s+)?(?:\d{1,2}|[ivxlcdm]{1,6})$",
    re.IGNORECASE,
)
_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)


def franchise_key(title: str) -> str | None:
    """The saga a title belongs to, or ``None`` when it does not look like one.

    A deliberately **conservative** heuristic, because the catalog has no
    franchise column: there is no ``collection`` on ``movies``, no series
    grouping on ``games``, and the Wikidata pass of feature 79 imported
    adaptations, not franchise membership.  So the signal has to come out of
    the title, and the cost of the two possible errors is not symmetric —
    missing a franchise loses a little diversity, while *inventing* one demotes
    an unrelated good result.  Only titles that announce themselves as part of
    a series get a key:

    - a subtitle after ``:`` or a spaced dash
      (``"The Lord of the Rings: The Return of the King"`` → ``lord of the rings``);
    - a trailing sequel number, arabic or roman
      (``"Mass Effect 2"`` → ``mass effect``, ``"Rocky IV"`` → ``rocky``).

    Everything else returns ``None`` and is never grouped with anything.  Note
    that the key is compared across types on purpose: the film, the novel and
    the game of one saga share it, which is where a cross-type list most needs
    the penalty.
    """
    if not title:
        return None
    head = _SUBTITLE_SPLIT.split(title.strip(), maxsplit=1)[0]
    had_subtitle = head != title.strip()
    normalised = _NON_WORD.sub(" ", head).strip()
    stripped = _SEQUEL_TAIL.sub("", normalised).strip()
    had_sequel_tail = stripped != normalised
    if not had_subtitle and not had_sequel_tail:
        return None
    key = " ".join(stripped.lower().split())
    # Leading articles are dropped so "The Witcher 3" and "Witcher: Wild Hunt"
    # land on the same key.
    for article in ("the ", "a ", "an ", "el ", "la ", "los ", "las "):
        if key.startswith(article):
            key = key[len(article) :]
            break
    # A one-or-two-character residue ("A 2", "IT: Chapter Two" → "it") is noise
    # that would group unrelated titles; refuse it.
    return key if len(key) >= 3 else None


def group_keys(candidate: Candidate) -> frozenset[tuple[str, object]]:
    """Every diversification group this candidate belongs to.

    A set and not a single key: an item can repeat a franchise *and* a creator,
    and both are legitimate reasons to demote it.  Namespaced by kind so a
    person id can never collide with a franchise string.
    """
    keys: set[tuple[str, object]] = {("creator", pid) for pid in candidate.creator_ids}
    franchise = franchise_key(candidate.title)
    if franchise is not None:
        keys.add(("franchise", franchise))
    return frozenset(keys)


def diversify(candidates: Sequence[Candidate], *, penalty: float) -> list[Candidate]:
    """Greedy re-rank that demotes a candidate for each group already taken.

    Every time a candidate shares a group with something already selected its
    score is multiplied by ``(1 - penalty)``, compounding per repetition, and
    the next pick is whatever now scores highest.  This is MMR with the
    redundancy term computed over discrete groups instead of over vectors —
    cheaper, and it expresses the rule the acceptance list actually asks for
    ("penalisation for a repeated franchise or author") rather than a generic
    vector-space spread.

    The penalty **demotes, it does not drop**.  A saga whose entries are the
    ten genuinely closest neighbours still fills the list rather than leaving
    it short; it just yields every slot it can to something else first.
    ``penalty <= 0`` disables the re-rank and returns the score order untouched.
    """
    ranked = sorted(candidates, key=lambda c: (-c.score, c.item_type, c.item_id))
    if penalty <= 0 or len(ranked) < 2:
        return ranked

    factor = max(0.0, 1.0 - penalty)
    remaining = list(ranked)
    taken_groups: dict[tuple[str, object], int] = {}
    selected: list[Candidate] = []

    while remaining:
        best_index = 0
        best_score = float("-inf")
        for index, candidate in enumerate(remaining):
            repeats = sum(taken_groups.get(key, 0) for key in group_keys(candidate))
            adjusted = candidate.score * (factor**repeats)
            if adjusted > best_score:
                best_score = adjusted
                best_index = index
        chosen = remaining.pop(best_index)
        for key in group_keys(chosen):
            taken_groups[key] = taken_groups.get(key, 0) + 1
        selected.append(chosen)
    return selected


def apply_cross_type_quota(
    anchor_type: str,
    ranked: Sequence[Candidate],
    *,
    limit: int,
    quota: int,
) -> list[Candidate]:
    """Reserve ``quota`` of the ``limit`` slots for items of another type.

    ``ranked`` arrives already ordered (diversified); the output preserves that
    order, so the quota decides **who** is in the page, never in what order the
    page reads.  A promoted cross-type item therefore appears where its own
    quality puts it, not pinned to the top — which is what keeps the list
    honest when the quota has to reach deep for a fourth type.

    The guarantee is "at least ``min(quota, limit, available)``".  It cannot be
    more than ``available``: if the whole catalog has two embedded books and
    nothing else of another type, no ranking can conjure a third.

    ``quota <= 0`` is the **default this feature merges with**, and it is not a
    stub: it is the same code path with nothing reserved, i.e. today's
    behaviour.  The value the ficha wants (3 of 10) is turned on by env in
    FE-67, in the same PR that renders the type badge — until then a book among
    films would be a link the web app builds as ``/movies/{book-slug}`` and
    404s.  See ``docs/api.md`` § Movies.
    """
    if limit <= 0:
        return []
    if quota <= 0:
        return list(ranked[:limit])

    # Positions, not objects: two candidates can compare equal (frozen
    # dataclass) without being the same row, and identity games would be a
    # subtle way to drop one of them.
    reserved = min(quota, limit)
    cross_positions = [i for i, c in enumerate(ranked) if c.item_type != anchor_type]
    chosen: set[int] = set(cross_positions[:reserved])

    room = limit - len(chosen)
    for position in range(len(ranked)):
        if room <= 0:
            break
        if position in chosen:
            continue
        chosen.add(position)
        room -= 1
    return [ranked[position] for position in sorted(chosen)]


def rank_similar(
    anchor_type: str,
    candidates: Iterable[Candidate],
    *,
    limit: int = SIMILAR_RESULT_LIMIT,
    quota: int = 0,
    penalty: float = 0.0,
) -> list[Candidate]:
    """Diversify, then enforce the cross-type quota, then cut to ``limit``."""
    pool = list(candidates)
    if not pool:
        return []
    diversified = diversify(pool, penalty=penalty)
    return apply_cross_type_quota(anchor_type, diversified, limit=limit, quota=quota)
