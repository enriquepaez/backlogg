"""Wikidata Query Service (SPARQL) client — the capa-2 knowledge source.

Feature 79.  Two questions, and only two:

1. **Which Wikidata entity is this catalog item?**  Asked by external id and
   never by title (``resolve_qids``), which is the whole reason this source was
   chosen: Wikidata stores TMDB, Open Library and IGDB identifiers, so the join
   against the catalog is an equality on an id rather than a fuzzy match on a
   string.  A title match would happily bind *The Thing* (1982) to *The Thing*
   (2011) and there would be no way to know afterwards.
2. **What does this entity say it is based on / what is derived from it?**
   (``fetch_relations``) — properties ``P144`` and ``P4969``.

Why the questions are asked *from* the catalog and not the other way round
-------------------------------------------------------------------------

The obvious implementation is "dump every ``P4947`` value in Wikidata and join
locally".  Measured against the live endpoint on 2026-09-14 that is 284.627
statements for TMDB movies, 63.703 for TMDB series, 512.900 for Open Library
and 1.033 for the numeric IGDB id — and paginating a dump that size needs a
sorted scan per page, which cost ~33 s for a single page of 5.000 rows and
comes uncomfortably close to the endpoint's 60 s query timeout.

Driving it from the catalog inverts that: a ``VALUES`` block of ids the
catalog actually holds turns each request into a set of index lookups, which
answers in well under a second, and it never downloads the ~750.000 statements
about items this catalog does not have.  It also makes resumability trivial,
because the cursor is then a position in **our** table (``external_ids.id``),
which is stable, totally ordered and cannot be reshuffled by an edit in
Wikidata mid-run.

Identifier properties
---------------------

======== =============== =========================================
type     property        value shape
======== =============== =========================================
MOVIE    ``P4947``       TMDB movie id (digits) — matches ours
SERIES   ``P4983``       TMDB TV series id (digits) — matches ours
BOOK     ``P648``        Open Library id; the work form ``OL…W``
                         is what the catalog stores
GAME     ``P9043``       IGDB **numeric** game id — matches ours
======== =============== =========================================

``P5794`` ("Internet Game Database game ID") is deliberately **not** used even
though it is 148x more populated than ``P9043``: its value is the IGDB *slug*
(``https://www.igdb.com/games/$1``), and this catalog's identity for a game is
the numeric IGDB id.  The only place the slug exists locally is ``games.slug``,
which is a display/URL slug that gets realigned when the source renames the
item (``docs/conventions.md``) — matching on it would be matching on a name.
Games therefore get a thin anchor, which is a *reported* number and not a
failure; the day an IGDB slug is persisted as an external id of its own, this
table grows one row and the coverage widens for free.

Politeness
----------

Same policy issue #26 imposed on Open Library: an identifying ``User-Agent``
with a contact address (the WDQS user-agent policy asks for exactly that and
blocks generic clients) plus a real rate limit, through the shared
``RequestPacer``.  WDQS publishes no req/s number — it enforces a concurrency
limit and a 60 s per-query timeout, and throttles with ``429`` plus
``Retry-After`` — so the pace here is deliberately conservative: this is a
monthly batch job with no user waiting on it, and being slow costs nothing.
Wikidata's data is CC0 and the endpoint is free, so the whole layer is at zero
cost.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backlogg.shared.pacing import RequestPacer

__all__ = [
    "ANCHOR_PROPERTIES",
    "RELATION_PROPERTIES",
    "WIKIDATA_QID_BATCH",
    "WIKIDATA_VALUES_BATCH",
    "RelationStatement",
    "WikidataClient",
    "is_qid",
]

logger = logging.getLogger(__name__)

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"

# WDQS blocks clients that do not identify themselves (its user-agent policy is
# the same one as the rest of the Wikimedia APIs).  Same string shape as the
# Open Library adapter's.
_WD_HEADERS = {
    "User-Agent": "backlogg/1.0 (https://github.com/enriquepaez/backlogg; contact@backlogg.app)",
    "Accept": "application/sparql-results+json",
}

# The endpoint kills a query at 60 s; allow a little more than that so a query
# that is *about* to be killed produces the server's own error rather than a
# client-side timeout that says nothing.
_WD_TIMEOUT = httpx.Timeout(75.0, connect=15.0)

_WD_MAX_RPS = 1.0

_WD_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_WD_RETRY_ATTEMPTS = 5

#: ``item_type -> (external source, Wikidata property)``.  See the module
#: docstring for why GAME uses ``P9043`` and not ``P5794``.
ANCHOR_PROPERTIES: dict[str, tuple[str, str]] = {
    "MOVIE": ("TMDB", "P4947"),
    "SERIES": ("TMDB", "P4983"),
    "BOOK": ("OPEN_LIBRARY", "P648"),
    "GAME": ("IGDB", "P9043"),
}

#: Wikidata property -> the ``item_relations.relation`` it becomes.
#: ``P144`` (*based on*): the subject is based on the object, so the edge runs
#: adaptation -> source work.  ``P4969`` (*derivative work*): the object is
#: derived from the subject, so the edge runs original -> derivative.
RELATION_PROPERTIES: dict[str, str] = {
    "P144": "ADAPTATION",
    "P4969": "DERIVATIVE",
}

# How many external ids travel in one ``VALUES`` block.  500 keeps the POST
# body around 5 KB and the query answers in well under a second; the endpoint's
# limit is wall clock, not payload, so the ceiling here is about keeping every
# single request comfortably inside the 60 s budget even on a bad day.
WIKIDATA_VALUES_BATCH = 500

# Same for the relations pass.  Smaller because each subject can fan out to
# several objects and the query touches two properties.
WIKIDATA_QID_BATCH = 250

_QID_RE = re.compile(r"^Q[1-9][0-9]*$")
# External ids are digits (TMDB, IGDB) or ``OL<digits><letter>`` (Open
# Library).  Anything else is refused rather than escaped: this string is
# interpolated into a SPARQL literal, and a value that does not look like an
# identifier is either corrupt data or an injection attempt.  There is no third
# case worth supporting.
_EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,100}$")
_ENTITY_PREFIX = "http://www.wikidata.org/entity/"


def is_qid(value: str) -> bool:
    """True for a canonical item QID (``Q42``).  Properties and lexemes are not."""
    return bool(_QID_RE.match(value))


@dataclass(frozen=True, slots=True)
class RelationStatement:
    """One ``subject property object`` triple, with both ends as bare QIDs."""

    from_qid: str
    property_id: str
    to_qid: str


def _is_wd_retryable_error(exc: BaseException) -> bool:
    """True for transient WDQS failures: 429/5xx, timeouts and transport errors.

    A 400 is never retried: WDQS answers a malformed or too-expensive query
    with 400, and re-sending it verbatim would just burn the endpoint's budget
    for the same answer.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _WD_RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


_wd_retry = retry(
    retry=retry_if_exception(_is_wd_retryable_error),
    stop=stop_after_attempt(_WD_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
)

# Process-wide, for the same reason as the Open Library pacer: the budget
# belongs to the endpoint, not to a client instance.
_wd_pacer = RequestPacer(_WD_MAX_RPS)


def _entity_qid(uri: str) -> str | None:
    """``http://www.wikidata.org/entity/Q42`` -> ``Q42``; anything else -> None.

    Returns None rather than raising for the values that legitimately are not
    items: ``P144`` can point at a statement node or, on a vandalised entity,
    at a literal.  Those are dropped, not fatal.
    """
    if not uri.startswith(_ENTITY_PREFIX):
        return None
    qid = uri[len(_ENTITY_PREFIX) :]
    return qid if is_qid(qid) else None


class WikidataClient:
    """Thin async SPARQL client.  One instance per call site is fine."""

    def __init__(self, endpoint: str = WDQS_ENDPOINT) -> None:
        self.endpoint = endpoint

    @_wd_retry
    async def _run_query(self, query: str) -> list[dict]:
        """POST one SPARQL query and return its ``results.bindings``.

        POST and not GET: a ``VALUES`` block of 500 ids makes a URL of several
        kilobytes, and WDQS's own documentation recommends POST past ~2 KB.
        """
        await _wd_pacer.wait()
        async with httpx.AsyncClient(timeout=_WD_TIMEOUT, headers=_WD_HEADERS) as client:
            response = await client.post(self.endpoint, data={"query": query})
            response.raise_for_status()
            payload = response.json()
        bindings = payload.get("results", {}).get("bindings", [])
        return list(bindings) if isinstance(bindings, list) else []

    async def resolve_qids(
        self, property_id: str, external_ids: Sequence[str]
    ) -> dict[str, list[str]]:
        """Map each external id to the QIDs that claim it, for one property.

        A **list** and not a single QID on purpose.  Wikidata occasionally
        carries the same TMDB id on two entities (an unmerged duplicate, or a
        film and its "film series" item).  Which of the two is the right one is
        not knowable from here, so the decision is pushed to the caller, which
        refuses ambiguity and counts it instead of guessing.

        Ids that are not present in Wikidata simply do not appear in the
        result — absence is the answer, and the caller reports it as coverage.
        """
        clean = [value for value in external_ids if _EXTERNAL_ID_RE.match(value)]
        rejected = len(external_ids) - len(clean)
        if rejected:
            logger.warning(
                "wikidata: %d external id(s) refused as unsafe for a SPARQL literal "
                "(property %s) — they look nothing like an identifier",
                rejected,
                property_id,
            )
        if not clean:
            return {}

        values = " ".join(f'"{value}"' for value in clean)
        query = (
            "SELECT ?item ?ext WHERE {\n"
            f"  VALUES ?ext {{ {values} }}\n"
            f"  ?item wdt:{property_id} ?ext .\n"
            "}"
        )
        resolved: dict[str, list[str]] = {}
        for binding in await self._run_query(query):
            qid = _entity_qid(binding.get("item", {}).get("value", ""))
            external_id = binding.get("ext", {}).get("value")
            if qid is None or not external_id:
                continue
            bucket = resolved.setdefault(external_id, [])
            if qid not in bucket:
                bucket.append(qid)
        return resolved

    async def fetch_relations(self, qids: Sequence[str]) -> list[RelationStatement]:
        """Every ``P144``/``P4969`` statement whose **subject** is one of ``qids``.

        Subject-only is not a gap.  An edge is kept only when *both* ends are
        in the catalog, and the pass walks every anchored QID the catalog has —
        so any edge with both ends local is found when its own subject comes up
        in its batch.  Asking for the inbound direction too would double the
        requests to rediscover the exact same statements.
        """
        clean = [qid for qid in qids if is_qid(qid)]
        if not clean:
            return []
        values = " ".join(f"wd:{qid}" for qid in clean)
        properties = " ".join(f"wdt:{prop}" for prop in sorted(RELATION_PROPERTIES))
        query = (
            "SELECT ?from ?prop ?to WHERE {\n"
            f"  VALUES ?from {{ {values} }}\n"
            f"  VALUES ?prop {{ {properties} }}\n"
            "  ?from ?prop ?to .\n"
            "}"
        )
        statements: list[RelationStatement] = []
        for binding in await self._run_query(query):
            from_qid = _entity_qid(binding.get("from", {}).get("value", ""))
            to_qid = _entity_qid(binding.get("to", {}).get("value", ""))
            prop = binding.get("prop", {}).get("value", "")
            property_id = prop.rsplit("/", 1)[-1] if prop else ""
            if from_qid is None or to_qid is None or property_id not in RELATION_PROPERTIES:
                continue
            statements.append(
                RelationStatement(from_qid=from_qid, property_id=property_id, to_qid=to_qid)
            )
        return statements
