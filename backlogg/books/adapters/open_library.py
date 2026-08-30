import asyncio
import logging
import re
import unicodedata
from collections import Counter
from datetime import UTC, date, datetime

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backlogg.books.constants import BOOK_LANGUAGE_EN, BOOK_LANGUAGE_ES
from backlogg.core.config import settings

_OL_BASE = "https://openlibrary.org"
_OL_COVER_BASE = "https://covers.openlibrary.org/b/id"
_OL_HEADERS = {
    "User-Agent": "backlogg/1.0 (https://github.com/enriquepaez/backlogg; contact@backlogg.app)",
}
_OL_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Field set requested from search.json. ``subject`` was dropped in feature 72:
# it was only ever consumed to derive genres, and those now come from the
# controlled ``lcc``/``ddc`` classifications with ``subject_facet`` as the
# filtered fallback (see _derive_genres). ``edition_count`` is not consumed by
# book_to_dict: it is the seed filter's discriminant (feature 73) and is
# requested so a returned page can be audited against the threshold that
# selected it. This is the shape book_to_dict consumes — keep it in sync with
# the hand-built search_doc in backlogg/scheduler/jobs.py::sync_books.
_OL_SEARCH_FIELDS = (
    "key,title,author_name,first_publish_year,cover_i,isbn,ddc,lcc,subject_facet,edition_count"
)

# Retry policy for the popular-books search: OL's Solr backend answers the
# readinglog-sorted seed query with intermittent 500s, and Issue #9
# showed those windows of degradation can last well over the ~30s a short
# retry budget covers (an offset that 500'd through 5 attempts in ~30s
# returned 200 again minutes later, unchanged). 8 attempts with exponential
# backoff (2/4/8/16/30/30/30s, capped at 30s/attempt) give ~120s of total
# retry budget instead.
_SEARCH_RETRY_ATTEMPTS = 8
_OL_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)


def _is_ol_retryable_error(exc: BaseException) -> bool:
    """True for transient Open Library failures: 429/5xx, timeouts and transport errors.

    Never retries a 4xx (e.g. a malformed query or rate-limit block that
    isn't a 429) — retrying would not fix a client error.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _OL_RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


_ol_search_retry = retry(
    retry=retry_if_exception(_is_ol_retryable_error),
    stop=stop_after_attempt(_SEARCH_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)

# ── Seed query construction (feature 73) ────────────────────────────────────
#
# The seed used to ask for ``q=*:*&sort=readinglog`` — "whatever most users
# shelved" — which drags in loose comic instalments, video-game tie-ins and
# half-empty records. It is now two *disjoint* filtered streams, English and
# Spanish, interleaved by quota. Why two and not one bilingual query: Open
# Library's ``language`` is multivalued **at work level** (it aggregates the
# languages of every edition), so ``language:(eng OR spa)`` is
# indistinguishable from ``language:eng`` (29.476 vs 29.326 hits) and returns
# the very same English list. A single readinglog-sorted query would seed zero
# Spanish works. Hence the Spanish stream carries ``NOT language:eng`` (making
# the two streams disjoint by construction, so the merge needs no dedup) and
# its own, ~10x lower, readinglog threshold.
#
# Page size stays at 100. ``limit=1000`` is accepted by search.json and was
# verified live to return 1000 docs, which would cut the request count 10x,
# but raising it is an unrelated optimization: it changes the pagination
# contract every caller test asserts on. Deliberately left as future work.
_OL_MAX_PAGE_SIZE = 100

# Open Library work keys end in ``W`` (``/works/OL82563W``). ``search.json``
# also returns the odd *edition* key (``/works/OL9394106M``, "Metal Gear Solid
# Volume 1"): editions with no parent work, exposed by the search index as if
# they were works. They are ~1 in 1.000 docs on an unfiltered stream and
# resolve to nothing useful downstream (``get_work_detail`` would 301 to the
# edition endpoint), so the seed drops them. Cheap safety net rather than a
# load-bearing filter: the calibrated thresholds already leave 0 of them in
# every sampled page.
_OL_WORK_KEY_SUFFIX = "W"


def _is_work_doc(doc: dict) -> bool:
    """True when a search doc is a real work, not an orphan edition key."""
    key = doc.get("key")
    return isinstance(key, str) and key.endswith(_OL_WORK_KEY_SUFFIX)


def build_seed_query(*, spanish: bool = False) -> str:
    """Build the Solr ``q`` for one of the two seed streams. Pure, no I/O.

    Thresholds are read from ``settings`` **at call time** (not captured at
    import time) so that a redeployed env var — or a test monkeypatch — takes
    effect without reimporting the module.

    The query is a plain conjunction of language, minimum length, minimum
    shelving count and minimum edition count. There is **no classification
    clause**: an earlier round filtered on ``(ddc:8* OR lcc:P*)`` and it was
    wrong in both directions — it dropped every essay and non-fiction title
    while letting comics through (LCC PN6700-6790 *is* "Comic books, graphic
    novels"). Filtering comics out in Solr is not possible either: ``lcc``
    takes no prefix wildcards, and ``subject_facet`` is returnable but not
    queryable. ``edition_count`` replaces all of it — it measures notoriety,
    which is the real discriminant, and it happens to subsume the
    record-completeness signals too (0 docs without cover/year/author in the
    sampled pages).

    Syntax is load-bearing and every rule below was measured against the live
    API: uppercase ``AND``/``OR``/``NOT`` (lowercase returns 0 hits) and
    unquoted range bounds (quoting them makes Solr parse the range as text
    and silently drop the filter). Encoding is left to ``httpx``, whose
    default form-encoding of spaces was verified to return the same
    ``numFound`` as percent-encoding.
    """
    if spanish:
        min_readinglog = settings.BOOKS_SEED_MIN_READINGLOG_ES
        min_editions = settings.BOOKS_SEED_MIN_EDITIONS_ES
    else:
        min_readinglog = settings.BOOKS_SEED_MIN_READINGLOG
        min_editions = settings.BOOKS_SEED_MIN_EDITIONS

    clauses = []
    if spanish:
        clauses.append(f"language:{BOOK_LANGUAGE_ES}")
        clauses.append(f"NOT language:{BOOK_LANGUAGE_EN}")
    else:
        clauses.append(f"language:{BOOK_LANGUAGE_EN}")
    clauses.append(f"number_of_pages_median:[{settings.BOOKS_SEED_MIN_PAGES} TO *]")
    clauses.append(f"readinglog_count:[{min_readinglog} TO *]")
    clauses.append(f"edition_count:[{min_editions} TO *]")
    return " AND ".join(clauses)


def is_spanish_slot(index: int, every_n: int) -> bool:
    """True when the global seed slot *index* belongs to the Spanish stream.

    One Spanish work every ``every_n`` slots, placed last inside each block
    so a slice of exactly ``every_n`` items always contains one. ``every_n``
    of 0 or less disables the Spanish stream entirely (English-only seed).
    """
    if every_n <= 0:
        return False
    return index % every_n == every_n - 1


def spanish_offset(index: int, every_n: int) -> int:
    """Number of Spanish slots before the global slot *index* (its sub-offset)."""
    if every_n <= 0:
        return 0
    return index // every_n


def english_offset(index: int, every_n: int) -> int:
    """Number of English slots before the global slot *index* (its sub-offset)."""
    if every_n <= 0:
        return index
    return index - index // every_n


def split_seed_slice(
    offset: int, limit: int, every_n: int
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Map a global ``(offset, limit)`` slice onto the two stream sub-slices.

    Returns ``((en_offset, en_count), (es_offset, es_count))``. Because the
    mapping is a pure function of the global index, the sync cursor in
    ``backlogg/scheduler/jobs.py`` stays a single integer: no per-stream
    cursor bookkeeping is needed.
    """
    end = offset + limit
    en_start = english_offset(offset, every_n)
    es_start = spanish_offset(offset, every_n)
    return (en_start, english_offset(end, every_n) - en_start), (
        es_start,
        spanish_offset(end, every_n) - es_start,
    )


def interleave_seed_slice(
    en_docs: list[dict], es_docs: list[dict], offset: int, limit: int, every_n: int
) -> list[dict]:
    """Merge both streams back into the global slot order given by ``is_spanish_slot``.

    When the stream a slot belongs to has run out, the slot is filled from
    the other stream instead of being left empty: a short page would make
    ``_next_offset`` in the sync job wrap the cursor back to 0 and stall the
    catalog. Pure, no I/O.
    """
    en_iter = iter(en_docs)
    es_iter = iter(es_docs)
    merged: list[dict] = []
    for index in range(offset, offset + limit):
        if is_spanish_slot(index, every_n):
            primary, secondary = es_iter, en_iter
        else:
            primary, secondary = en_iter, es_iter
        doc = next(primary, None)
        if doc is None:
            doc = next(secondary, None)
        if doc is None:
            break
        merged.append(doc)
    return merged


# ── Book classification (feature 72) ────────────────────────────────────────
#
# Genres used to be derived from Open Library's ``subject`` field, an
# uncontrolled folksonomy averaging ~40 tags per work: 370 ingested books
# produced 510 distinct labels, 397 of them used exactly once ("Triathlon",
# "Concentration camps", "Country homes"). They are now derived from the two
# controlled, hierarchical classifications ``search.json`` already exposes —
# LCC (Library of Congress, 89% coverage) and DDC (Dewey, 78%) — with the
# cleaner-but-still-folksonomic ``subject_facet`` (99%) used only as a net,
# and only when it matches this same controlled vocabulary.

# The closed, user-facing vocabulary: slug -> display name. Nothing outside
# this table can ever reach ``book_genres``. Kept small and auditable on
# purpose; it is the coarse axis (fiction vs essay, literature vs psychology
# vs history), not reader-facing genre (fantasy/horror/romance), which DDC and
# LCC structurally cannot express — see the module docstring of
# ``_derive_genres`` and features 76-78.
_CONTROLLED_GENRES: dict[str, str] = {
    "fiction": "Fiction",
    "poetry": "Poetry",
    "drama": "Drama",
    "essays": "Essays",
    "literature": "Literature",
    "childrens-young-adult": "Children's & Young Adult",
    "philosophy": "Philosophy",
    "psychology": "Psychology",
    "self-help": "Self-Help",
    "religion": "Religion",
    "history": "History",
    "biography": "Biography",
    "geography-travel": "Geography & Travel",
    "social-sciences": "Social Sciences",
    "economics-business": "Economics & Business",
    "political-science": "Political Science",
    "law": "Law",
    "education": "Education",
    "music": "Music",
    "art": "Art",
    "language": "Language",
    "science": "Science",
    "mathematics": "Mathematics",
    "computing": "Computing",
    "medicine-health": "Medicine & Health",
    "technology": "Technology",
    "agriculture": "Agriculture",
    "cooking": "Cooking",
    "military-naval": "Military & Naval",
    "sports-recreation": "Sports & Recreation",
    "reference": "Reference",
    "library-information-science": "Library & Information Science",
}

# LCC letter class -> vocabulary slugs. Looked up most-specific-first (3, then
# 2, then 1 letter), so "PZ" wins over "P" and "P" catches PA..PT.
_LCC_CLASS_GENRES: dict[str, tuple[str, ...]] = {
    # A — general works, encyclopaedias, indexes
    "A": ("reference",),
    # B — philosophy, psychology, religion
    "B": ("philosophy",),
    "BC": ("philosophy",),  # logic
    "BD": ("philosophy",),  # speculative philosophy
    "BF": ("psychology",),
    "BH": ("philosophy",),  # aesthetics
    "BJ": ("philosophy",),  # ethics
    "BL": ("religion",),
    "BM": ("religion",),
    "BP": ("religion",),
    "BQ": ("religion",),
    "BR": ("religion",),
    "BS": ("religion",),
    "BT": ("religion",),
    "BV": ("religion",),
    "BX": ("religion",),
    # C — auxiliary sciences of history (CT is collective biography)
    "C": ("history",),
    "CT": ("biography",),
    # D/E/F — world history and history of the Americas
    "D": ("history",),
    "E": ("history",),
    "F": ("history",),
    # G — geography, anthropology, recreation
    "G": ("geography-travel",),
    "GN": ("social-sciences",),  # anthropology
    "GR": ("social-sciences",),  # folklore
    "GV": ("sports-recreation",),
    # H — social sciences; HB..HJ is the economics/business run
    "H": ("social-sciences",),
    "HB": ("economics-business",),
    "HC": ("economics-business",),
    "HD": ("economics-business",),
    "HE": ("economics-business",),
    "HF": ("economics-business",),
    "HG": ("economics-business",),
    "HJ": ("economics-business",),
    # J/K/L — political science, law, education
    "J": ("political-science",),
    "K": ("law",),
    "L": ("education",),
    # M/N — music and fine arts
    "M": ("music",),
    "N": ("art",),
    # P — language and literature. PB..PM are languages, PA/PG..PT are
    # literatures, PZ is fiction and juvenile belles lettres — which of the
    # two depends on the class *number*, see _LCC_PZ_SUBDIVISION_GENRES.
    "P": ("language",),
    "PA": ("literature",),
    "PB": ("language",),
    "PC": ("language",),
    "PD": ("language",),
    "PE": ("language",),
    "PF": ("language",),
    "PG": ("literature",),
    "PH": ("language",),
    "PJ": ("literature",),
    "PK": ("literature",),
    "PL": ("literature",),
    "PM": ("language",),
    "PN": ("literature",),
    "PQ": ("literature",),
    "PR": ("literature",),
    "PS": ("literature",),
    "PT": ("literature",),
    # PZ is listed here only so the most-specific-first prefix lookup stops
    # at it instead of falling back to "P" (language). Its value is the one
    # thing the whole class shares; a real PZ entry is resolved by
    # _lcc_entry_key into a _LCC_PZ_SUBDIVISION_GENRES key instead.
    "PZ": ("fiction",),
    # Q — science; QA is mathematics
    "Q": ("science",),
    "QA": ("mathematics",),
    # R/S/T — medicine, agriculture, technology (TX is home economics/cookery)
    "R": ("medicine-health",),
    "S": ("agriculture",),
    "T": ("technology",),
    "TX": ("cooking",),
    # U/V — military and naval science
    "U": ("military-naval",),
    "V": ("military-naval",),
    # Z — bibliography and library science
    "Z": ("library-information-science",),
}

# PZ subdivision -> vocabulary slugs. Unlike every other LCC class, PZ's
# number changes what the class *means*:
#
#   PZ1-PZ4     fiction in English for **adults** — an older LCC practice that
#               is still all over Open Library's records. The Shining carries
#               "PZ-0004...", L'étranger "PZ-0003...".
#   PZ5-PZ10.3  juvenile belles lettres, i.e. genuinely children's/YA. PZ7 is
#               juvenile fiction (Harry Potter, The Fault in Our Stars), and
#               PZ10.3 — normalized by OL as "PZ-0010.73100000" — is juvenile
#               non-fiction. Both sit above the threshold.
#
# Mapping the whole class to children's is what put The Shining, L'étranger
# and Fifty Shades of Grey under "Children's & Young Adult" in the dev
# re-ingest (42 of 96 books).
_LCC_PZ_ADULT_KEY = "PZ1-4"
_LCC_PZ_JUVENILE_KEY = "PZ5+"
_LCC_PZ_JUVENILE_MIN = 5.0
_LCC_PZ_SUBDIVISION_GENRES: dict[str, tuple[str, ...]] = {
    _LCC_PZ_ADULT_KEY: ("fiction",),
    _LCC_PZ_JUVENILE_KEY: ("fiction", "childrens-young-adult"),
}

# DDC numeric prefix -> vocabulary slugs, longest prefix first. The 8xx
# literature class is handled separately by ``_ddc_literature_genres`` because
# there the *third* digit encodes literary form, not subject.
_DDC_PREFIX_GENRES: dict[str, tuple[str, ...]] = {
    # Refinements that would otherwise be lost inside their century
    "004": ("computing",),
    "005": ("computing",),
    "006": ("computing",),
    "158": ("self-help",),  # applied psychology / self-help
    "641": ("cooking",),
    "796": ("sports-recreation",),
    "920": ("biography",),
    "929": ("history",),  # genealogy, names, heraldry — not biography
    "92": ("biography",),  # the abridged 2-digit biography notation
    "15": ("psychology",),  # 150-159, the psychology half of the 1xx class
    "78": ("music",),
    "91": ("geography-travel",),  # 910-919 geography and travel
    # Centuries
    "0": ("reference",),
    "1": ("philosophy",),
    "2": ("religion",),
    "3": ("social-sciences",),
    "4": ("language",),
    "5": ("science",),
    "6": ("technology",),
    "7": ("art",),
    "9": ("history",),
}

# 8xx: the digit after the language digit is the literary *form*, and unlike
# the rest of DDC it maps onto something a reader recognises. It is the one
# signal LCC cannot carry, so it also refines the LCC literature classes —
# see ``_ddc_literary_form_slugs`` and ``_derive_genres``.
_DDC_LITERARY_FORM_GENRES: dict[str, tuple[str, ...]] = {
    "1": ("poetry", "literature"),
    "2": ("drama", "literature"),
    "3": ("fiction", "literature"),
    "4": ("essays", "literature"),
}

# Bracketed DDC notations Open Library returns for fiction/easy readers.
_DDC_BRACKET_GENRES: dict[str, tuple[str, ...]] = {
    "fic": ("fiction",),
    "e": ("childrens-young-adult",),
}

# ``subject_facet`` values accepted as classification, exact match after
# case-folding and whitespace collapsing. Deliberately an exact-match table
# and not a substring/heuristic filter: this field is still a folksonomy, and
# the whole point of feature 72 is that nothing uncontrolled gets persisted.
# A book whose facets match nothing here simply ends up with no genres.
_SUBJECT_FACET_GENRES: dict[str, tuple[str, ...]] = {
    "fiction": ("fiction",),
    "novel": ("fiction",),
    "novels": ("fiction",),
    "literary fiction": ("fiction", "literature"),
    "juvenile fiction": ("fiction", "childrens-young-adult"),
    "young adult fiction": ("fiction", "childrens-young-adult"),
    "children's fiction": ("fiction", "childrens-young-adult"),
    "children's literature": ("childrens-young-adult",),
    "children's stories": ("childrens-young-adult",),
    "juvenile literature": ("childrens-young-adult",),
    "literature": ("literature",),
    "poetry": ("poetry",),
    "drama": ("drama",),
    "plays": ("drama",),
    "essays": ("essays",),
    "biography": ("biography",),
    "biographies": ("biography",),
    "autobiography": ("biography",),
    "memoirs": ("biography",),
    "history": ("history",),
    "military history": ("history", "military-naval"),
    "philosophy": ("philosophy",),
    "psychology": ("psychology",),
    "self-help": ("self-help",),
    "self-help techniques": ("self-help",),
    "conduct of life": ("self-help",),
    "religion": ("religion",),
    "christianity": ("religion",),
    "spirituality": ("religion",),
    "science": ("science",),
    "nature": ("science",),
    "mathematics": ("mathematics",),
    "computers": ("computing",),
    "computer science": ("computing",),
    "programming": ("computing",),
    "technology": ("technology",),
    "medicine": ("medicine-health",),
    "health": ("medicine-health",),
    "health & fitness": ("medicine-health",),
    "business": ("economics-business",),
    "business & economics": ("economics-business",),
    "economics": ("economics-business",),
    "management": ("economics-business",),
    "finance": ("economics-business",),
    "political science": ("political-science",),
    "politics": ("political-science",),
    "law": ("law",),
    "education": ("education",),
    "music": ("music",),
    "art": ("art",),
    "language": ("language",),
    "languages": ("language",),
    "social science": ("social-sciences",),
    "social sciences": ("social-sciences",),
    "sociology": ("social-sciences",),
    "cooking": ("cooking",),
    "cookbooks": ("cooking",),
    "cookery": ("cooking",),
    "travel": ("geography-travel",),
    "voyages and travels": ("geography-travel",),
    "description and travel": ("geography-travel",),
    "geography": ("geography-travel",),
    "sports": ("sports-recreation",),
    "sports & recreation": ("sports-recreation",),
    "games": ("sports-recreation",),
    "agriculture": ("agriculture",),
    "reference": ("reference",),
}

# Cap kept from the previous implementation. Since the lcc path now emits
# only the dominant class (at most literary form + class = 3 slugs), the cap
# is only ever reachable through the multivalued ddc path.
_MAX_GENRES = 5

# One normalized LCC call number: the letter class plus the zero-padded,
# possibly decimal class number Open Library puts in the second position.
# "PZ-0007.00000000.R79835 Har 1998" -> ("PZ", "0007.00000000").
_LCC_ENTRY_RE = re.compile(r"^([A-Z]{1,3})-?\s*(\d+(?:\.\d+)?)?")
_DDC_BRACKET_RE = re.compile(r"^\[([A-Za-z]+)\]")
_WHITESPACE_RE = re.compile(r"\s+")


def _as_str_list(value: object) -> list[str]:
    """Coerce an Open Library search-doc field into a list of strings.

    ``search.json`` returns ``ddc``/``lcc``/``subject_facet`` as lists, but a
    single string (or a missing/None value, or a list with non-string junk in
    it) must never raise here — classification is best-effort metadata.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _lcc_class_key(letters: str) -> str | None:
    """Most specific mapped LCC prefix of *letters* (3, then 2, then 1 letter).

    ``"HD"`` wins over ``"H"`` and ``"PZ"`` over ``"P"``. ``None`` when no
    prefix is in ``_LCC_CLASS_GENRES``.
    """
    for size in (3, 2, 1):
        prefix = letters[:size]
        if prefix in _LCC_CLASS_GENRES:
            return prefix
    return None


def _lcc_pz_key(number: str | None) -> str:
    """Resolve the class number of a PZ call number to its subdivision key.

    ``PZ5`` and above is juvenile belles lettres; ``PZ1``-``PZ4`` is fiction
    in English for adults. Open Library normalizes the number into the second
    position with zero padding, so ``"PZ-0007.00000000.R79835 Har 1998"``
    yields ``"0007.00000000"`` -> 7.0 (juvenile) and ``"PZ-0010.73100000"``
    (PZ10.3) yields 10.731 (also juvenile), while ``"PZ-0004.00000000.K5227
    Sh"`` yields 4.0 (adult fiction).

    A missing or unparseable number falls back to the **adult** key, i.e.
    plain "Fiction". That is the label the whole PZ class shares and therefore
    the only safe assertion; inferring "children's" from a number that could
    not be read is precisely the mistake that mislabelled 42 of 96 re-ingested
    books, and it is the more damaging of the two errors (a novel filed as
    children's misleads; a children's book filed as fiction is merely coarse).
    """
    if number is None:
        return _LCC_PZ_ADULT_KEY
    try:
        value = float(number)
    except ValueError:
        return _LCC_PZ_ADULT_KEY
    return _LCC_PZ_JUVENILE_KEY if value >= _LCC_PZ_JUVENILE_MIN else _LCC_PZ_ADULT_KEY


def _lcc_entry_key(raw: str) -> str | None:
    """Classification key of a single normalized LCC call number.

    The key is the most specific mapped letter prefix, except for ``PZ``,
    where it is the subdivision key (``_lcc_pz_key``) because there the number
    decides the meaning. Returns ``None`` for anything that does not parse or
    whose class is not in the mapping tables — an unmapped class must not take
    part in (let alone win) the vote in ``_lcc_genre_slugs``.
    """
    match = _LCC_ENTRY_RE.match(raw.strip().upper())
    if not match:
        return None
    key = _lcc_class_key(match.group(1))
    if key is None:
        return None
    if key == "PZ":
        return _lcc_pz_key(match.group(2))
    return key


def _lcc_key_genres(key: str) -> tuple[str, ...]:
    """Vocabulary slugs for a key produced by ``_lcc_entry_key``."""
    subdivided = _LCC_PZ_SUBDIVISION_GENRES.get(key)
    if subdivided is not None:
        return subdivided
    return _LCC_CLASS_GENRES.get(key, ())


def _lcc_genre_slugs(lcc_values: object) -> list[str]:
    """Map an Open Library ``lcc`` list to the slugs of its *dominant* class.

    Open Library returns LCC in its sortable normalized form
    (``"PS-3568.00000000.O243 D3 1998"``) and contributes one entry per
    edition, so the list is routinely multivalued *and* mixed: measured over
    the 100 most-shelved works, 87 carry ``lcc`` and 45 of those 87 (51%)
    carry more than one distinct class. Multivalue is the majority case, not
    an edge case.

    Aggregating every class in the list therefore let one oddly shelved
    edition speak for the whole work: L'étranger carries 42 entries, 40 of
    class ``PQ`` (French literature) and 2 of class ``PZ`` from a school
    edition, and those 2 were enough to label Camus as children's. The Shining
    had 11 ``PS`` against 3 ``PZ``. So the classes are counted and only the
    **most frequent** one is emitted; minority classes contribute nothing.

    Ties are broken by **first appearance in the list**: deterministic, stable
    across runs, and independent of any set/dict iteration order.
    ``Counter.most_common`` is deliberately not used — it makes no guarantee
    about the relative order of equally frequent keys.

    Entries that do not parse, or whose class is not in the mapping tables,
    are skipped and never counted. ``PZ`` votes as its two subdivisions
    (``PZ1-4`` and ``PZ5+``) rather than as a single class, so its entries
    split: ``PQ``x3 + ``PZ1-4``x2 + ``PZ5+``x2 is won by ``PQ``. That is the
    intended, conservative behaviour — telling the two halves apart is the
    reason the subdivision exists.
    """
    keys = [key for key in (_lcc_entry_key(raw) for raw in _as_str_list(lcc_values)) if key]
    if not keys:
        return []
    counts = Counter(keys)
    top_count = max(counts.values())
    dominant = next(key for key in keys if counts[key] == top_count)
    return list(_lcc_key_genres(dominant))


def _ddc_genre_slugs(ddc_values: object) -> list[str]:
    """Map Dewey Decimal notations to vocabulary slugs.

    Open Library returns values like ``"813.54"`` or ``"813/.54"`` (the slash
    marks the segmentation point and is stripped), plus the occasional
    bracketed ``"[Fic]"``/``"[E]"`` notation.

    Classes map by hundreds (0 generalities, 1 philosophy, 2 religion,
    3 social sciences, 4 language, 5 science, 6 technology, 7 arts,
    8 literature, 9 history & geography), with a handful of refinements that
    would otherwise be lost inside their century (computing, biography,
    cooking, music, sports, travel, psychology/self-help). Inside 8xx the
    third digit is the literary *form* — see ``_DDC_LITERARY_FORM_GENRES``.
    """
    slugs: list[str] = []
    for raw in _as_str_list(ddc_values):
        candidate = raw.strip()
        bracket = _DDC_BRACKET_RE.match(candidate)
        if bracket:
            slugs.extend(_DDC_BRACKET_GENRES.get(bracket.group(1).lower(), ()))
            continue
        digits = candidate.replace("/", "").replace(".", "")
        digits = "".join(ch for ch in digits if ch.isdigit())
        if not digits:
            continue
        if digits[0] == "8":
            slugs.extend(_ddc_literature_genres(digits))
            continue
        for size in (3, 2, 1):
            mapped = _DDC_PREFIX_GENRES.get(digits[:size])
            if mapped:
                slugs.extend(mapped)
                break
    return slugs


def _ddc_literature_genres(digits: str) -> tuple[str, ...]:
    """Resolve an 8xx (literature) Dewey number to vocabulary slugs.

    In 8xx the second digit is the language and the third is the literary
    form: ``8_1`` poetry, ``8_2`` drama, ``8_3`` fiction, ``8_4`` essays. So
    ``813.54`` is American English fiction. Forms outside that set (speeches,
    letters, satire, miscellany) and the 80x general/theory range fall back to
    the plain "Literature" label.
    """
    if len(digits) >= 3 and digits[1] != "0":
        mapped = _DDC_LITERARY_FORM_GENRES.get(digits[2])
        if mapped:
            return mapped
    return ("literature",)


def _ddc_literary_form_slugs(ddc_values: object) -> list[str]:
    """Extract *only* the literary-form signal from an 8xx Dewey number.

    Used by ``_derive_genres`` to refine an LCC literature class. LCC files
    literature by provenance and language (``PR`` English literature, ``PS``
    American literature) and structurally never encodes form; DDC puts the
    form in the third digit of ``8xx``. The two fields are therefore
    complementary at this one point, and only here.

    Returns an empty list when there is no ``ddc``, when it is not a
    literature number, or when its form digit is not one of the four known
    ones — "no form signal" is a valid answer, not a failure.
    """
    for raw in _as_str_list(ddc_values):
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) < 3 or digits[0] != "8" or digits[1] == "0":
            continue
        mapped = _DDC_LITERARY_FORM_GENRES.get(digits[2])
        if mapped:
            return list(mapped)
    return []


def _subject_facet_genre_slugs(facet_values: object) -> list[str]:
    """Map ``subject_facet`` values onto the controlled vocabulary.

    Exact match only, case-insensitive and with collapsed whitespace. Values
    that don't match are dropped: ``subject_facet`` is cleaner than ``subject``
    but still a folksonomy, and letting it through raw is precisely the bug
    feature 72 removes.
    """
    slugs: list[str] = []
    for raw in _as_str_list(facet_values):
        key = _WHITESPACE_RE.sub(" ", raw.strip().lower())
        slugs.extend(_SUBJECT_FACET_GENRES.get(key, ()))
    return slugs


def _controlled_slugs(slugs: list[str]) -> list[str]:
    """Keep only slugs that exist in the closed vocabulary, order preserved.

    Applied to every source *before* the precedence decision in
    ``_derive_genres``. If a mapping table ever gains a typo'd slug, the
    source that produced it must count as empty so the next one can answer,
    instead of silently leaving the book with no genres at all.
    """
    return [slug for slug in slugs if slug in _CONTROLLED_GENRES]


def _derive_genres(search_doc: dict) -> list[dict]:
    """Derive up to ``_MAX_GENRES`` controlled genres from an OL search doc.

    ``lcc`` decides the discipline, ``ddc`` is its fallback:

    1. ``lcc`` (Library of Congress Classification, 89% coverage on the 200
       most-shelved works). Primary because it is the most complete of the two
       controlled taxonomies and its letter classes map cleanly onto the
       vocabulary.

       Only the **dominant** class of the ``lcc`` list is used, never the
       union of all of them. Open Library contributes one entry per edition
       and 45 of the 87 works with ``lcc`` in the 100 most-shelved sample
       (51%) carry more than one distinct class, so aggregating let a single
       stray edition speak for the work — 2 ``PZ`` entries out of L'étranger's
       42 turned Camus into children's literature. The most frequent class
       wins; ties go to the class that appears first in the list. The one
       class whose *number* is also read is ``PZ``: PZ1-PZ4 is adult fiction,
       PZ5 and above juvenile belles lettres. See ``_lcc_genre_slugs`` and
       ``_lcc_pz_key``.
    2. When — and only when — the dominant LCC class resolves to
       ``literature``, the literary-form digit of ``ddc`` is read *in
       addition*, and prepended.
       This is not a merge of two taxonomies: LCC files literature by
       provenance and language (``PR`` is English literature, ``PS`` American
       literature) and never encodes form, while DDC encodes exactly that in
       the third digit of ``8xx`` (``8_1`` poetry, ``8_2`` drama, ``8_3``
       fiction, ``8_4`` essays). The two fields are complementary at this one
       point and nowhere else, so "Fiction" refines "Literature" instead of
       contradicting or replacing it — the discipline still comes from LCC.
       Without this, a novel, a poetry collection and a book of essays shelved
       under ``PS`` would all come out as plain "Literature", i.e. the
       fiction-vs-essay axis would only ever be delivered for the ~11% of books
       with no ``lcc`` at all. If the record has no ``ddc``, or its form digit
       is not one of the four above, the book stays at plain "Literature":
       that is the honest answer when there is no form signal.

       Outside the literature classes both taxonomies classify by discipline,
       so there they would only produce near-duplicate labels; the refinement
       is deliberately scoped and never applied elsewhere. Because it keys off
       the dominant class only, a secondary ``PS`` on a mathematics book can
       no longer make it come out as "Fiction".
    3. ``ddc`` (Dewey, 78%) as the source, when ``lcc`` is missing or its class
       is unmapped.
    4. ``subject_facet`` (99%), filtered against the same closed vocabulary.
       Covers the works with neither classification. If nothing matches, the
       book gets no genres at all — an accepted, and much better, outcome than
       persisting folksonomy noise.

    Each source is filtered against ``_CONTROLLED_GENRES`` *before* it is
    checked for emptiness, so a bad entry in a mapping table degrades into the
    next source rather than into a silently genre-less book.

    Known and deliberate limit: DDC and LCC classify by discipline and
    provenance, not by reader-facing genre. ``813.6`` is "contemporary
    American fiction", so *It Ends With Us* and Stephen King's *It* share a
    classification. This function delivers the coarse, clean axis (fiction vs
    essay, literature vs psychology vs history); fantasy/horror/romance is the
    job of features 76-78 and must not be faked here.
    """
    slugs = _controlled_slugs(_lcc_genre_slugs(search_doc.get("lcc")))
    if slugs:
        if "literature" in slugs:
            form = _controlled_slugs(_ddc_literary_form_slugs(search_doc.get("ddc")))
            slugs = form + slugs
    else:
        slugs = _controlled_slugs(_ddc_genre_slugs(search_doc.get("ddc")))
        if not slugs:
            slugs = _controlled_slugs(_subject_facet_genre_slugs(search_doc.get("subject_facet")))

    genres: list[dict] = []
    seen: set[str] = set()
    for slug in slugs:
        if slug in seen:
            continue
        seen.add(slug)
        genres.append({"name": _CONTROLLED_GENRES[slug], "slug": slug})
        if len(genres) >= _MAX_GENRES:
            break
    return genres


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _normalize_edition_as_work(edition: dict) -> dict:
    """Reshape an Open Library edition JSON into work-shaped fields.

    Used by ``get_work_detail`` when the ``work_id`` it was given only
    exists as a standalone edition (``/books/{id}.json``) — confirmed
    against real Open Library responses for the Issue #10 IDs, editions
    never carry ``description`` or ``first_publish_date``/nested-``author``
    ``authors``, so those are reshaped/backfilled here:

    - ``authors``: edition shape is a flat ``[{"key": "/authors/OL..A"}]``;
      work shape (consumed by ``_persist_book_authors``) is
      ``[{"author": {"key": "/authors/OL..A"}}]``.
    - ``first_publish_date``: editions use ``publish_date`` instead; copied
      over only when ``first_publish_date`` is absent, so a genuine work
      value is never overwritten.
    - ``description``: editions don't have one; left absent, which
      ``book_to_dict`` already handles (``overview`` stays ``None``).
    """
    normalized = dict(edition)
    authors = edition.get("authors")
    if authors:
        normalized["authors"] = [
            {"author": {"key": entry["key"]}}
            for entry in authors
            if isinstance(entry, dict) and entry.get("key")
        ]
    if "first_publish_date" not in normalized and normalized.get("publish_date"):
        normalized["first_publish_date"] = normalized["publish_date"]
    return normalized


class OpenLibraryClient:
    @_ol_search_retry
    async def search_book(self, title: str, page: int = 1, limit: int = 1) -> list[dict]:
        """Search Open Library by title and return up to *limit* results for *page*.

        Not affected by the Issue #10 redirect bug: this hits the
        ``/search.json`` query endpoint (same as ``_fetch_popular_page``),
        not a per-ID detail lookup like ``/works/{id}.json`` or
        ``/authors/{id}.json`` — a search query has no OLID to be the wrong
        record type for, so it never receives the routing-mismatch 301.
        ``follow_redirects`` is deliberately left out.

        Defaults to ``limit=1`` (top hit only) for the on-demand single-item
        fallback callers (``books/service.py``); the search fan-out
        (``search/service.py``) passes an explicit ``page``/``limit`` to walk
        further pages. Retried via ``_ol_search_retry`` like the other
        ``search.json`` caller in this module.
        """
        async with httpx.AsyncClient(headers=_OL_HEADERS, timeout=_OL_TIMEOUT) as client:
            response = await client.get(
                f"{_OL_BASE}/search.json",
                params={
                    "title": title,
                    "fields": _OL_SEARCH_FIELDS,
                    "limit": limit,
                    "page": page,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("docs", [])

    @_ol_search_retry
    async def _fetch_popular_page(self, query: str, per_page: int, offset: int) -> dict:
        """Fetch one page of the popular-books search, retrying transient failures.

        429/5xx responses, timeouts and transport errors are retried up to
        ``_SEARCH_RETRY_ATTEMPTS`` times with exponential backoff via
        ``tenacity`` (OL's Solr is flaky on this query; a retry after a
        short wait consistently succeeds — see Issue #9 for a case where the
        degradation window outlasted a smaller retry budget). A failure that
        survives every retry — and any other 4xx (e.g. a 403 rate-limit),
        which a retry would not fix — raises ``httpx.HTTPStatusError``:
        callers must never mistake a failed fetch for an exhausted listing.

        ``query`` is one of the two streams built by ``build_seed_query``;
        it is passed in rather than built here so a single page fetch stays
        stream-agnostic.
        """
        params = {
            "q": query,
            "sort": "readinglog",
            "fields": _OL_SEARCH_FIELDS,
            "limit": per_page,
            "offset": offset,
        }
        async with httpx.AsyncClient(headers=_OL_HEADERS, timeout=_OL_TIMEOUT) as client:
            response = await client.get(f"{_OL_BASE}/search.json", params=params)
        response.raise_for_status()
        return response.json()

    async def _fetch_seed_stream(
        self, query: str, offset: int, count: int, label: str
    ) -> tuple[list[dict], int | None, int]:
        """Fetch *count* consecutive docs of one seed stream starting at *offset*.

        Returns ``(docs, num_found, next_offset)``:

        - ``docs``: up to *count* usable search docs.
        - ``num_found``: the stream's ``numFound``, ``None`` when no request
          was needed because *count* was not positive. ``get_popular_books``
          uses it for the pool-size guard.
        - ``next_offset``: the **raw API offset** just past the last document
          consumed. It is *not* ``offset + len(docs)``: dropped docs still
          advance the API cursor. Callers that want to keep reading this
          stream must use this value — see below.

        Orphan edition keys (``_is_work_doc``) are dropped **here**, inside
        the pagination loop, and not by the caller. That placement is what
        makes the drop self-healing: the loop keeps requesting until it holds
        *count* usable docs, so a discarded doc is replaced by the next one in
        the stream. Filtering in ``get_popular_books`` instead would shrink an
        already-counted slot budget and hand the sync job a short page with
        neither stream exhausted — which ``_next_offset`` reads as
        end-of-listing and answers by wrapping the cursor back to 0.

        Two counters live here and they are deliberately different: the API
        cursor and end-of-results (``len(docs) < per_page``, the only signal
        OL gives) are in **raw doc space**, while ``results`` is in
        **filtered** space. Mixing them either skips or re-requests
        documents, so ``next_offset`` is returned rather than left for the
        caller to reconstruct — reconstructing it as ``offset + len(docs)``
        is precisely the bug this signature prevents (the exhaustion backfill
        in ``get_popular_books`` re-requested the last *D* docs it had just
        returned, duplicating them inside a single page).
        """
        if count <= 0:
            return [], None, offset

        results: list[dict] = []
        num_found: int | None = None
        cursor = offset
        while len(results) < count:
            per_page = min(count - len(results), _OL_MAX_PAGE_SIZE)
            data = await self._fetch_popular_page(query, per_page, cursor)
            if num_found is None:
                num_found = data.get("numFound")
            docs = data.get("docs", [])
            if not docs:
                logger.info("get_popular_books: no more %s results at offset %d", label, cursor)
                break
            work_docs = [doc for doc in docs if _is_work_doc(doc)]
            if len(work_docs) < len(docs):
                logger.info(
                    "get_popular_books: dropped %d non-work key(s) from the %s stream at offset %d",
                    len(docs) - len(work_docs),
                    label,
                    cursor,
                )
            results.extend(work_docs)
            # Advance by the raw page, never by the kept docs. ``results`` can
            # never overshoot ``count`` (each page asks for exactly the
            # remainder and filtering only shrinks it), so the cursor always
            # ends up just past the last doc actually returned by the API.
            cursor += len(docs)
            if len(docs) < per_page:
                break

        return results[:count], num_found, cursor

    async def get_popular_books(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Fetch popular books from Open Library for nightly sync.

        Uses ``GET /search.json`` sorted by ``readinglog`` — how many users
        shelved the work as want-to-read/reading/read — which surfaces
        genuinely popular works and supports deep native offset/limit
        pagination (verified past offset 100.000), unlike the old
        ``/trending/weekly.json`` listing that was capped at a few hundred
        entries.

        The match-all ``q=*:*`` was replaced in feature 73 by two filtered,
        disjoint streams (``build_seed_query``): raw readinglog popularity
        drags in loose comic instalments, video-game tie-ins and half-empty
        records. Both streams are restricted by language, minimum length,
        minimum shelving count and minimum edition count, and are interleaved
        by ``interleave_seed_slice`` so Spanish works appear from the first
        slice on. The interleaving is a pure function of the global index, so
        the caller's cursor stays a single integer.

        Returns search docs with the same field set as ``search_book``
        (``_OL_SEARCH_FIELDS``), which is the shape ``book_to_dict``
        consumes.

        Raises ``httpx.HTTPStatusError`` when a page request keeps failing
        after exhausting the retries (or fails with a non-retryable 4xx),
        even mid-pagination: the pages accumulated so far are discarded so a
        returned list always means a fully successful fetch — a 200 response
        with fewer docs than requested is the only legitimate end-of-results
        signal.  Discarding is safe because nothing has been persisted yet,
        upserts are idempotent and the sync cursor is not advanced on error,
        so the next run refetches the same slice.
        """
        every_n = settings.BOOKS_SEED_ES_EVERY_N
        (en_offset, en_count), (es_offset, es_count) = split_seed_slice(offset, limit, every_n)
        en_query = build_seed_query(spanish=False)
        es_query = build_seed_query(spanish=True)

        # ``en_next``/``es_next`` are raw API offsets, not ``offset + len(docs)``:
        # the orphan-key drop advances the API cursor without producing a doc,
        # so only the stream itself knows where it stopped reading.
        en_docs, en_found, en_next = await self._fetch_seed_stream(
            en_query, en_offset, en_count, "english"
        )
        es_docs, es_found, es_next = await self._fetch_seed_stream(
            es_query, es_offset, es_count, "spanish"
        )

        # Pool guard. Nothing else reads numFound, and without this check a
        # filtered pool smaller than SEED_TOP_N_BOOKS would fail *silently*:
        # past the last result OL answers 200 with an empty docs list, the
        # caller sees a short page, wraps its cursor to 0 and re-syncs the
        # same books every night while never reaching the target (the same
        # failure mode /trending/weekly.json had in feature 25). The
        # thresholds are env-tunable, so someone may well tighten them past
        # that point.
        if en_found is not None and es_found is not None:
            pool = en_found + es_found
            if pool < settings.SEED_TOP_N_BOOKS:
                logger.warning(
                    "get_popular_books: filtered pool (%d english + %d spanish = %d) is "
                    "smaller than SEED_TOP_N_BOOKS (%d); the sync cursor will wrap before "
                    "reaching the target — lower BOOKS_SEED_MIN_READINGLOG/"
                    "BOOKS_SEED_MIN_READINGLOG_ES/BOOKS_SEED_MIN_PAGES/"
                    "BOOKS_SEED_MIN_EDITIONS/BOOKS_SEED_MIN_EDITIONS_ES",
                    en_found,
                    es_found,
                    pool,
                    settings.SEED_TOP_N_BOOKS,
                )

        # Exhaustion fallback: a stream that runs out hands its remaining
        # slots to the other one, which resumes from the raw offset it
        # actually stopped at (``en_next``/``es_next``, returned by the fetch
        # — *not* ``en_offset + len(en_docs)``, which is filtered space and
        # would re-request every doc the orphan-key drop skipped, duplicating
        # it inside this same page). The page is then not returned short,
        # which the caller would read as end-of-listing. Warned once per call.
        #
        # Backfilling *into* spanish slots is gated on ``every_n > 0``: with
        # the spanish stream switched off, ``es_count`` is 0 and the second
        # branch's ``len(es_docs) == es_count`` would hold trivially, firing
        # the spanish query the kill switch exists to avoid. That switch is
        # there for "Open Library broke the spanish query", where emitting it
        # anyway would burn the whole retry budget and fail the slice. Note
        # the asymmetry is deliberate: ``every_n = 1`` is a quota setting
        # (every slot is spanish), not a kill switch for english, and nothing
        # promises it disables that stream.
        if len(es_docs) < es_count and len(en_docs) == en_count:
            extra, _, _ = await self._fetch_seed_stream(
                en_query, en_next, es_count - len(es_docs), "english"
            )
            if extra:
                logger.warning(
                    "get_popular_books: spanish stream exhausted at offset %d; "
                    "backfilled %d slot(s) from the english stream",
                    es_next,
                    len(extra),
                )
            en_docs.extend(extra)
        elif every_n > 0 and len(en_docs) < en_count and len(es_docs) == es_count:
            extra, _, _ = await self._fetch_seed_stream(
                es_query, es_next, en_count - len(en_docs), "spanish"
            )
            if extra:
                logger.warning(
                    "get_popular_books: english stream exhausted at offset %d; "
                    "backfilled %d slot(s) from the spanish stream",
                    en_next,
                    len(extra),
                )
            es_docs.extend(extra)

        return interleave_seed_slice(en_docs, es_docs, offset, limit, every_n)

    async def get_work_detail(self, work_id: str) -> dict | None:
        """Fetch full work detail from Open Library.

        ``work_id`` is the bare OLID like ``OL123W`` (without the /works/ prefix).

        Some ``work_id`` values returned by ``search.json`` are actually
        edition OLIDs (suffix ``M``, not ``W``) that only exist as a
        standalone edition record with no work of their own — Open Library
        answers ``GET /works/{id}.json`` for these with a ``301`` to
        ``GET /books/{id}.json`` (confirmed in production, Issue #10).
        ``follow_redirects=True`` follows it instead of letting
        ``raise_for_status()`` turn the unfollowed redirect into an
        exception. An edition response has a different shape than a work
        response — ``authors`` is a flat ``[{"key": ...}]`` list instead of
        the work's ``[{"author": {"key": ...}}]``, dates live in
        ``publish_date`` instead of ``first_publish_date``, and editions
        carry no ``description`` — so it's normalized into work shape by
        ``_normalize_edition_as_work`` before being returned, so callers
        (``_persist_book_authors``, ``book_to_dict``) don't need to
        special-case it.
        """
        async with httpx.AsyncClient(
            headers=_OL_HEADERS, timeout=_OL_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(f"{_OL_BASE}/works/{work_id}.json")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            detail = response.json()
            if detail.get("type", {}).get("key") == "/type/edition":
                detail = _normalize_edition_as_work(detail)
            return detail

    async def get_author(self, author_id: str) -> dict | None:
        """Fetch author detail from Open Library.

        ``author_id`` is the bare OLID like ``OL123A`` (without the /authors/ prefix).
        Retries up to 3 times on timeout before returning None.

        Follows redirects (``follow_redirects=True``) for consistency with
        ``get_work_detail``: Open Library merges duplicate author records,
        and this client shares the exact same "AsyncClient without
        follow_redirects" pattern that caused Issue #10 for work details.
        No production 301 has been observed here (spot-checked against
        several live author IDs), but the fix is a no-op when unneeded and
        closes the same class of bug defensively.
        """
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    headers=_OL_HEADERS, timeout=_OL_TIMEOUT, follow_redirects=True
                ) as client:
                    response = await client.get(f"{_OL_BASE}/authors/{author_id}.json")
                    if response.status_code == 404:
                        return None
                    response.raise_for_status()
                    return response.json()
            except httpx.TimeoutException:
                if attempt < 2:
                    await asyncio.sleep(1)
                else:
                    logger.warning("get_author: timeout after 3 attempts for %s", author_id)
                    return None
        return None  # unreachable, satisfies type checker

    def book_to_dict(self, search_doc: dict, work_detail: dict | None = None) -> dict:
        """Convert Open Library search doc (+ optional work detail) to a DB-ready dict."""
        title = search_doc.get("title", "")
        first_publish_year = search_doc.get("first_publish_year")

        # Parse first_publish_date — Open Library only gives us a year from search
        first_publish_date: date | None = None
        year_str: str = ""
        if first_publish_year:
            try:
                year = int(first_publish_year)
                first_publish_date = date(year, 1, 1)
                year_str = str(year)
            except (ValueError, TypeError):
                first_publish_date = None

        # If work detail has a more specific date, use it
        if work_detail:
            raw_date = work_detail.get("first_publish_date")
            if raw_date:
                # Try common formats: "2003", "2003-01", "January 2003", "2003-01-15"
                parsed = _parse_ol_date(raw_date)
                if parsed:
                    first_publish_date = parsed
                    year_str = str(parsed.year)

        # Build slug from title and year
        slug_base = _slugify(title)
        slug = f"{slug_base}-{year_str}" if year_str else slug_base

        # Cover image from search result (cover_i is an integer cover ID)
        cover_i = search_doc.get("cover_i")
        poster_url = f"{_OL_COVER_BASE}/{cover_i}-L.jpg" if cover_i else None

        # Synopsis from work detail
        overview: str | None = None
        if work_detail:
            desc = work_detail.get("description")
            if isinstance(desc, str):
                overview = desc or None
            elif isinstance(desc, dict):
                overview = desc.get("value") or None

        # ISBN from search doc. Open Library returns a list — a work can have
        # several editions/ISBNs. Feature 71 decision: persist the first one
        # as-is, with no ISBN-13/ISBN-10 preference. search.json already
        # orders `isbn` by edition relevance for the matched work, so the
        # first entry is a reasonable canonical pick without adding a
        # priority pass; revisit only if real data shows this picks a poor
        # edition in practice.
        isbn_list = search_doc.get("isbn", [])
        isbn = isbn_list[0] if isbn_list else None

        # Genres from the controlled LCC/DDC classifications, with a filtered
        # subject_facet fallback — see _derive_genres (feature 72).
        genres = _derive_genres(search_doc)

        # Open Library has no aggregate rating — leave as None
        return {
            "title": title,
            "original_title": None,
            "slug": slug,
            "overview": overview,
            "first_publish_date": first_publish_date,
            "original_language": None,
            "poster_url": poster_url,
            "isbn": isbn,
            "rating_external": None,
            "rating_count_external": None,
            "rating_internal": None,
            "rating_count_internal": 0,
            "last_synced_at": datetime.now(UTC),
            "genres": genres,
        }


def _parse_ol_date(raw: str) -> date | None:
    """Try to parse Open Library date strings into a Python date.

    Handles formats like "2003", "January 2003", "2003-01-15", "2003-01".
    Returns None when parsing fails.
    """
    raw = raw.strip()

    # ISO date: YYYY-MM-DD
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass

    # Year only: YYYY
    if re.fullmatch(r"\d{4}", raw):
        try:
            return date(int(raw), 1, 1)
        except ValueError:
            pass

    # Year-Month: YYYY-MM
    m = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass

    # "Month YYYY" or "Month Day, YYYY"
    import calendar

    months = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
    month_pattern = "|".join(months)
    m2 = re.search(rf"({month_pattern})\s+(?:\d{{1,2}},\s*)?(\d{{4}})", raw, re.IGNORECASE)
    if m2:
        try:
            month_num = months[m2.group(1).lower()]
            year_num = int(m2.group(2))
            return date(year_num, month_num, 1)
        except (ValueError, KeyError):
            pass

    return None
