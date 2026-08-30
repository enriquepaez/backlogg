"""Tests for the OpenLibraryClient adapter.

Covers:
- User-Agent header is sent in get_popular_books requests
- get_popular_books queries /search.json with the feature-73 filtered seed
  queries (english + spanish streams), sort=readinglog and native
  offset/limit, requesting the field set book_to_dict consumes
- build_seed_query renders both streams verbatim, reading the thresholds from
  settings at call time, and carries no ddc/lcc classification clause (the
  round-1 filter, reverted: it excluded non-fiction and let comics through)
- orphan edition keys (/works/OL...M) are dropped inside the pagination loop,
  so a drop is topped up instead of shortening the page — and only shortens
  it when the stream is genuinely exhausted
- split_seed_slice / interleave_seed_slice map a global (offset, limit) slice
  onto the two streams and back, including the stream-exhaustion fallback
- get_popular_books raises immediately (no retry) when the API responds with 403
- get_popular_books retries transient 5xx responses (via tenacity) and
  succeeds on a later attempt
- get_popular_books tolerates a long 5xx burst and still succeeds within the
  widened tenacity retry window (recovers on the 8th attempt)
- get_popular_books raises after exhausting the tenacity retries, including
  mid-pagination (accumulated pages are discarded, never returned as success)
- get_popular_books correctly parses a response containing a non-empty "docs" list
- get_author retries on TimeoutException and returns None after 3 failures
- get_author succeeds on a retry after an initial timeout
- get_author returns None on 404
- get_work_detail follows a 301 redirect from /works/{id}.json to
  /books/{id}.json (Issue #10) instead of raising, and normalizes the
  edition response into work shape (authors, first_publish_date)
- get_work_detail returns a work response unmodified (no redirect involved)
- get_work_detail returns None on 404
- get_author follows a 301 redirect (defensive consistency fix, Issue #10)
- genres are derived from the controlled lcc/ddc/subject_facet taxonomies
  (feature 72): lcc drives the discipline, ddc refines literary form inside
  the literature classes only, and every mapping table stays inside the
  closed vocabulary
- a multivalued lcc list (the majority case: 51% of the works that carry lcc
  carry more than one class) resolves to its dominant class, ties broken by
  first appearance, and the PZ class is split by its number — PZ1-PZ4 is
  adult fiction, PZ5+ juvenile belles lettres
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backlogg.books.adapters import open_library as ol_adapter
from backlogg.books.adapters.open_library import (
    _CONTROLLED_GENRES,
    _DDC_BRACKET_GENRES,
    _DDC_LITERARY_FORM_GENRES,
    _DDC_PREFIX_GENRES,
    _LCC_CLASS_GENRES,
    _LCC_PZ_SUBDIVISION_GENRES,
    _OL_HEADERS,
    _OL_SEARCH_FIELDS,
    _SUBJECT_FACET_GENRES,
    OpenLibraryClient,
    _is_work_doc,
    build_seed_query,
    interleave_seed_slice,
    is_spanish_slot,
    split_seed_slice,
)
from backlogg.books.service import _persist_book_authors
from backlogg.core.config import Settings, settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    """Build a lightweight mock that mimics an httpx.Response."""
    response = MagicMock()
    response.status_code = status_code
    if json_data is not None:
        response.json = MagicMock(return_value=json_data)
    if status_code >= 400:
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status_code}", request=MagicMock(), response=response
            )
        )
    else:
        response.raise_for_status = MagicMock()
    return response


def _search_payload(docs: list[dict]) -> dict:
    return {"numFound": len(docs), "docs": docs}


def _is_spanish_query(params: dict | None) -> bool:
    """True when the captured request belongs to the spanish seed stream.

    Feature 73 turned the single ``q=*:*`` seed into two disjoint streams, so
    tests that only care about one of them (retry budget, pagination) tell
    them apart by the language clause instead of by call order.
    """
    return "language:spa" in (params or {}).get("q", "")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_popular_books_sends_user_agent_header():
    """get_popular_books must include the User-Agent header in its HTTP request."""

    async def fake_get(url, params=None):  # noqa: ARG001
        return _mock_response(200, _search_payload([]))

    mock_client = AsyncMock()
    mock_client.get = fake_get

    # Capture the headers passed to AsyncClient's constructor
    original_headers: dict = {}

    class CapturingClient:
        def __init__(self, headers=None, **kwargs):
            nonlocal original_headers
            original_headers = headers or {}

        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, *args):
            pass

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", CapturingClient):
        client = OpenLibraryClient()
        await client.get_popular_books(limit=1)

    assert "User-Agent" in original_headers
    assert original_headers["User-Agent"] == _OL_HEADERS["User-Agent"]


@pytest.mark.asyncio
async def test_get_popular_books_queries_both_filtered_streams_with_readinglog_sort(
    calibrated_thresholds,
):
    """get_popular_books must hit /search.json once per seed stream (feature 73).

    Each request carries its stream's filtered query, sort=readinglog, the
    field set consumed by book_to_dict and the stream's own sub-offset/limit
    derived from the global (offset, limit) slice — not the raw global ones.
    """
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            calls.append({"url": url, "params": params})
            return _mock_response(200, _search_payload([]))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        await client.get_popular_books(limit=25, offset=120)

    assert len(calls) == 2
    english, spanish = calls
    for call in calls:
        assert call["url"].endswith("/search.json")
        assert call["params"]["sort"] == "readinglog"
        assert call["params"]["fields"] == _OL_SEARCH_FIELDS

    # Global slots 120..144 with BOOKS_SEED_ES_EVERY_N=10 hold 23 english
    # works (sub-offset 120 - 12 = 108) and 2 spanish ones (sub-offset 12).
    assert english["params"]["q"] == build_seed_query()
    assert english["params"]["offset"] == 108
    assert english["params"]["limit"] == 23
    assert spanish["params"]["q"] == build_seed_query(spanish=True)
    assert spanish["params"]["offset"] == 12
    assert spanish["params"]["limit"] == 2


@pytest.mark.asyncio
async def test_get_popular_books_raises_on_403_without_retry():
    """A 4xx (e.g. rate-limit 403) must raise immediately — no retry, no [] masking."""
    call_count = 0

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            return _mock_response(403)

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_popular_books(limit=10)

    assert call_count == 1  # 4xx is not retried


@pytest.mark.asyncio
async def test_get_popular_books_retries_5xx_and_succeeds_on_second_attempt():
    """A transient 5xx must be retried via tenacity; the 2nd attempt's 200 is returned.

    Scoped to the english stream: the spanish one answers empty so the result
    is exactly the retried page.
    """
    fake_docs = [{"key": "/works/OL1W", "title": "Book One"}]
    call_count = 0

    class FlakyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            if _is_spanish_query(params):
                return _mock_response(200, _search_payload([]))
            if call_count == 1:
                return _mock_response(500)
            return _mock_response(200, _search_payload(fake_docs))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FlakyClient):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            client = OpenLibraryClient()
            result = await client.get_popular_books(limit=10)

    assert result == fake_docs
    assert call_count == 3  # 500 + 200 on the english stream, 1 empty spanish page
    mock_sleep.assert_awaited_once()  # one backoff between the two attempts


@pytest.mark.asyncio
async def test_get_popular_books_raises_after_persistent_5xx():
    """A 5xx that survives all tenacity retry attempts must raise, never return []."""
    call_count = 0

    class BrokenClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            return _mock_response(500)

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", BrokenClient):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            client = OpenLibraryClient()
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_popular_books(limit=10)

    assert call_count == 8  # initial attempt + 7 retries (widened budget, Issue #9)


@pytest.mark.asyncio
async def test_get_popular_books_recovers_after_long_5xx_burst():
    """A long 5xx burst that clears on the 7th attempt must still succeed.

    The retry window was widened from 5 to 8 attempts (Issue #9) precisely
    to absorb longer OL Solr 5xx bursts than the old budget survived: six
    consecutive 500s followed by a 200 must return the docs, not raise.
    """
    fake_docs = [{"key": "/works/OL1W", "title": "Book One"}]
    call_count = 0

    class LongBurstClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            if _is_spanish_query(params):
                return _mock_response(200, _search_payload([]))
            if call_count < 7:
                return _mock_response(500)
            return _mock_response(200, _search_payload(fake_docs))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", LongBurstClient):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            client = OpenLibraryClient()
            result = await client.get_popular_books(limit=10)

    assert result == fake_docs
    # six 500s absorbed and a 200 on the seventh attempt (english stream),
    # plus the single empty spanish page
    assert call_count == 8
    assert mock_sleep.await_count == 6  # one backoff between each of the 7 attempts


@pytest.mark.asyncio
async def test_get_popular_books_mid_pagination_error_discards_and_raises():
    """A persistent 5xx on a later page raises and discards earlier pages.

    A returned list must always mean a fully successful fetch: returning the
    accumulated pages would look like a legitimate short (end-of-results)
    response upstream and wrap the sync cursor to 0.
    """
    page_one = [{"key": f"/works/OL{i}W", "title": f"Book {i}"} for i in range(100)]
    call_count = 0

    class FlakySecondPageClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            if params["offset"] == 0:
                return _mock_response(200, _search_payload(page_one))
            return _mock_response(500)

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FlakySecondPageClient):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            client = OpenLibraryClient()
            with pytest.raises(httpx.HTTPStatusError):
                await client.get_popular_books(limit=200, offset=0)

    # Page 1 OK + 8 failed attempts on page 2 (Issue #9 budget). The english
    # stream is fetched first and raises, so the spanish one is never reached.
    assert call_count == 9


@pytest.mark.asyncio
async def test_get_popular_books_parses_docs_list():
    """get_popular_books must return the list of search docs from a successful response."""
    fake_docs = [
        {
            "key": "/works/OL1W",
            "title": "Book One",
            "author_name": ["Author One"],
            "first_publish_year": 1999,
            "cover_i": 111,
            "lcc": ["PR-6068.00000000.O93 H37 1997"],
            "ddc": ["823.914"],
            "subject_facet": ["Fiction"],
        },
        {
            "key": "/works/OL2W",
            "title": "Book Two",
            "author_name": ["Author Two"],
            "first_publish_year": 2005,
            "cover_i": 222,
            "lcc": ["PS-3568.00000000.O243 D3 1998"],
            "ddc": ["813.54"],
            "subject_facet": ["Fiction"],
        },
    ]

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            if _is_spanish_query(params):
                return _mock_response(200, _search_payload([]))
            # Return fewer items than per_page so the loop terminates after one page
            return _mock_response(200, _search_payload(fake_docs))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    assert len(result) == 2
    assert result[0]["key"] == "/works/OL1W"
    assert result[1]["title"] == "Book Two"
    # Each doc carries the fields book_to_dict consumes
    for doc in result:
        assert {
            "key",
            "title",
            "author_name",
            "first_publish_year",
            "cover_i",
            "lcc",
            "ddc",
            "subject_facet",
        } <= set(doc)


# ---------------------------------------------------------------------------
# Feature 73: books_seeding_quality_filter — seed query + stream interleaving
# ---------------------------------------------------------------------------


@pytest.fixture
def calibrated_thresholds(monkeypatch):
    """Pin the seed thresholds to their shipped defaults.

    Settings are loaded from the local .env, which an operator may have
    overridden; these tests assert the calibrated query, not the machine's
    configuration.
    """
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_READINGLOG", 20)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_READINGLOG_ES", 5)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_PAGES", 100)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_EDITIONS", 10)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_EDITIONS_ES", 2)
    monkeypatch.setattr(settings, "BOOKS_SEED_ES_EVERY_N", 10)


def test_seed_threshold_defaults_are_the_calibrated_values():
    """The shipped defaults must be the live-measured ones, ignoring any local .env.

    16.959 english + 1.858 spanish works, a pool ~190x SEED_TOP_N_BOOKS's
    default, with the spanish quota matching the spanish share of that pool
    (1.858/18.817 ~ 10%).
    """
    defaults = Settings(_env_file=None)

    assert defaults.BOOKS_SEED_MIN_READINGLOG == 20
    assert defaults.BOOKS_SEED_MIN_READINGLOG_ES == 5
    assert defaults.BOOKS_SEED_MIN_PAGES == 100
    assert defaults.BOOKS_SEED_MIN_EDITIONS == 10
    assert defaults.BOOKS_SEED_MIN_EDITIONS_ES == 2
    assert defaults.BOOKS_SEED_ES_EVERY_N == 10


def test_spanish_edition_floor_keeps_the_two_edition_control(calibrated_thresholds):
    """BOOKS_SEED_MIN_EDITIONS_ES must stay at 2: Reina roja has exactly 2 editions.

    Raising it to 3 nearly halves the spanish pool (1.858 -> 976) and expels a
    control title that must be seeded, so the floor is pinned by a test rather
    than left to a reviewer to remember.
    """
    assert settings.BOOKS_SEED_MIN_EDITIONS_ES <= 2
    assert "edition_count:[2 TO *]" in build_seed_query(spanish=True)


def test_build_seed_query_english_renders_the_calibrated_query(calibrated_thresholds):
    """The english stream query must be rendered verbatim, thresholds included.

    This exact string was measured live against search.json and returns
    16.959 works. Asserting it character by character is deliberate: every
    syntax detail is load-bearing. Note what is *absent*: no classification
    clause. Filtering by ddc/lcc was tried and reverted — it dropped every
    essay and non-fiction title while letting comics through, and no
    comics-only signature is queryable in Solr anyway. ``edition_count`` is
    the notoriety discriminant that replaced it.
    """
    assert build_seed_query() == (
        "language:eng "
        "AND number_of_pages_median:[100 TO *] "
        "AND readinglog_count:[20 TO *] "
        "AND edition_count:[10 TO *]"
    )


def test_build_seed_query_spanish_renders_the_calibrated_query(calibrated_thresholds):
    """The spanish stream must exclude english works and use its own threshold.

    ``NOT language:eng`` is what makes the two streams disjoint (OL's
    ``language`` is multivalued at work level, so ``language:spa`` alone
    returns the english list), and the lower readinglog and edition floors are
    what make the stream non-empty: this exact string returns 1.858 works.
    """
    assert build_seed_query(spanish=True) == (
        "language:spa AND NOT language:eng "
        "AND number_of_pages_median:[100 TO *] "
        "AND readinglog_count:[5 TO *] "
        "AND edition_count:[2 TO *]"
    )


@pytest.mark.parametrize("spanish", [False, True])
def test_build_seed_query_respects_solr_syntax_rules(spanish):
    """Uppercase operators and unquoted range bounds, both measured live.

    Lowercase ``and``/``or`` returns 0 hits and a quoted range is parsed as
    text and silently ignored (``readinglog_count:"[20 TO *]"`` -> 947.088
    hits, i.e. no filter at all).
    """
    query = build_seed_query(spanish=spanish)

    assert " and " not in query
    assert " or " not in query
    assert " not " not in query
    assert query.startswith(f"language:{'spa' if spanish else 'eng'}")
    assert '"' not in query
    assert "TO *]" in query


@pytest.mark.parametrize("spanish", [False, True])
def test_build_seed_query_carries_no_classification_clause(spanish):
    """No ddc/lcc clause may come back: it excluded non-fiction and kept comics.

    ``(ddc:8* OR lcc:P*)`` was the round-1 filter and it was wrong in both
    directions — Atomic Habits (ddc 155.24) and Sapiens fell out while
    Watchmen came in through LCC PN6737, which *is* the comics range. Solr
    offers no working alternative either: ``lcc`` takes no prefix wildcards
    (``lcc:PN-67*`` -> 0 hits; escaped, a longer prefix returns *more* docs)
    and ``subject_facet`` is returnable but not queryable.
    """
    query = build_seed_query(spanish=spanish)

    assert "ddc" not in query
    assert "lcc" not in query


def test_build_seed_query_reads_thresholds_from_settings(monkeypatch):
    """Thresholds come from settings at call time, so env overrides take effect."""
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_READINGLOG", 200)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_READINGLOG_ES", 2)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_PAGES", 150)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_EDITIONS", 25)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_EDITIONS_ES", 7)

    assert "readinglog_count:[200 TO *]" in build_seed_query()
    assert "number_of_pages_median:[150 TO *]" in build_seed_query()
    assert "edition_count:[25 TO *]" in build_seed_query()
    assert "readinglog_count:[2 TO *]" in build_seed_query(spanish=True)
    assert "number_of_pages_median:[150 TO *]" in build_seed_query(spanish=True)
    assert "edition_count:[7 TO *]" in build_seed_query(spanish=True)


def test_is_spanish_slot_places_one_spanish_work_per_block():
    """One spanish slot every N, last in the block, so every N-sized slice has one."""
    slots = [is_spanish_slot(i, 10) for i in range(20)]

    assert [i for i, es in enumerate(slots) if es] == [9, 19]


def test_is_spanish_slot_disabled_when_every_n_is_zero():
    """every_n <= 0 disables the spanish stream instead of dividing by zero."""
    assert [is_spanish_slot(i, 0) for i in range(5)] == [False] * 5


@pytest.mark.parametrize(
    ("offset", "limit", "every_n", "expected"),
    [
        # First slice: 90 english + 10 spanish, both from their own offset 0.
        (0, 100, 10, ((0, 90), (0, 10))),
        # Second slice: each stream resumes exactly where the first one left.
        (100, 100, 10, ((90, 90), (10, 10))),
        # Slice shorter than a block and not covering slot N-1: english only.
        (0, 5, 10, ((0, 5), (0, 0))),
        # Slice starting mid-block, crossing exactly one spanish slot.
        (5, 10, 10, ((5, 9), (0, 1))),
        # Deep offset: sub-offsets stay consistent with the global index.
        (1000, 200, 10, ((900, 180), (100, 20))),
        # every_n=1 makes the seed spanish-only.
        (0, 10, 1, ((0, 0), (0, 10))),
        # every_n=0 disables the spanish stream entirely.
        (0, 10, 0, ((0, 10), (0, 0))),
    ],
)
def test_split_seed_slice_maps_global_slice_onto_both_streams(offset, limit, every_n, expected):
    """A global (offset, limit) maps to disjoint, gap-free sub-slices per stream."""
    assert split_seed_slice(offset, limit, every_n) == expected


@pytest.mark.parametrize("offset", [0, 1, 7, 9, 10, 99, 100, 137, 1000])
def test_split_seed_slice_sub_offsets_are_contiguous_across_slices(offset):
    """Consecutive slices must not skip or repeat a doc in either stream."""
    limit = 25
    (en_start, en_count), (es_start, es_count) = split_seed_slice(offset, limit, 10)
    (next_en_start, _), (next_es_start, _) = split_seed_slice(offset + limit, limit, 10)

    assert en_count + es_count == limit
    assert next_en_start == en_start + en_count
    assert next_es_start == es_start + es_count


def test_interleave_seed_slice_places_spanish_docs_on_their_slots():
    """The merged page follows the global slot order, spanish last in each block."""
    en_docs = [{"key": f"en{i}"} for i in range(9)]
    es_docs = [{"key": "es0"}]

    merged = interleave_seed_slice(en_docs, es_docs, 0, 10, 10)

    assert [doc["key"] for doc in merged] == [f"en{i}" for i in range(9)] + ["es0"]


def test_interleave_seed_slice_honours_a_non_zero_global_offset():
    """Slot parity is computed from the global index, not from the page index."""
    en_docs = [{"key": f"en{i}"} for i in range(4)]
    es_docs = [{"key": "es0"}]

    # Global slots 7..11: only slot 9 is spanish.
    merged = interleave_seed_slice(en_docs, es_docs, 7, 5, 10)

    assert [doc["key"] for doc in merged] == ["en0", "en1", "es0", "en2", "en3"]


def test_interleave_seed_slice_fills_gaps_when_the_spanish_stream_is_exhausted():
    """An exhausted stream must not shorten the page: the other one fills the slot.

    A short page is read upstream as end-of-listing and wraps the sync cursor
    back to 0, stalling the catalog silently.
    """
    en_docs = [{"key": f"en{i}"} for i in range(10)]

    merged = interleave_seed_slice(en_docs, [], 0, 10, 10)

    assert [doc["key"] for doc in merged] == [f"en{i}" for i in range(10)]


def test_interleave_seed_slice_fills_gaps_when_the_english_stream_is_exhausted():
    """Symmetric fallback: spanish docs cover the english slots when needed."""
    es_docs = [{"key": f"es{i}"} for i in range(5)]

    merged = interleave_seed_slice([{"key": "en0"}], es_docs, 0, 6, 10)

    assert [doc["key"] for doc in merged] == ["en0", "es0", "es1", "es2", "es3", "es4"]


def test_interleave_seed_slice_returns_short_page_only_when_both_streams_run_out():
    """With nothing left in either stream the merge stops instead of padding."""
    merged = interleave_seed_slice([{"key": "en0"}], [{"key": "es0"}], 0, 10, 10)

    assert [doc["key"] for doc in merged] == ["en0", "es0"]


@pytest.mark.asyncio
async def test_get_popular_books_interleaves_both_streams(calibrated_thresholds):
    """End to end: the returned page carries spanish works on their slots."""
    en_docs = [{"key": f"/works/EN{i}W", "title": f"English {i}"} for i in range(9)]
    es_docs = [{"key": "/works/ES0W", "title": "Spanish 0"}]

    class TwoStreamClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            docs = es_docs if _is_spanish_query(params) else en_docs
            return _mock_response(200, _search_payload(docs))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", TwoStreamClient):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    assert [doc["key"] for doc in result] == [f"/works/EN{i}W" for i in range(9)] + ["/works/ES0W"]


@pytest.mark.asyncio
async def test_get_popular_books_backfills_from_english_when_spanish_is_exhausted(
    calibrated_thresholds,
):
    """An exhausted spanish stream is backfilled from english, keeping the page full."""
    calls: list[dict] = []

    class ExhaustedSpanishClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            calls.append(params)
            if _is_spanish_query(params):
                return _mock_response(200, {"numFound": 0, "docs": []})
            offset = params["offset"]
            docs = [
                {"key": f"/works/EN{offset + i}W"}
                for i in range(min(params["limit"], 200 - offset))
            ]
            return _mock_response(200, {"numFound": 200, "docs": docs})

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", ExhaustedSpanishClient):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    assert len(result) == 10  # never short: the cursor upstream must keep advancing
    assert [doc["key"] for doc in result] == [f"/works/EN{i}W" for i in range(10)]
    # english page (9) + empty spanish page + english backfill of the 1 gap
    assert len(calls) == 3
    assert calls[2]["offset"] == 9
    assert calls[2]["limit"] == 1


@pytest.mark.asyncio
async def test_get_popular_books_never_queries_spanish_when_every_n_is_zero(monkeypatch):
    """BOOKS_SEED_ES_EVERY_N=0 must keep the spanish query off the wire entirely.

    The kill switch exists for "Open Library broke the spanish query": if the
    exhaustion backfill still emitted it, a persistent 5xx on that query would
    burn the retry budget and fail the whole slice. The regression it guards
    against is subtle — with every_n=0 the spanish quota is 0, so the
    backfill's ``len(es_docs) == es_count`` check (0 == 0) held trivially and
    a short english page was enough to fire the query. Asserted on the
    captured requests, not just on the returned docs: a spanish doc could
    also be absent simply because the fake returned none.
    """
    monkeypatch.setattr(settings, "BOOKS_SEED_ES_EVERY_N", 0)
    calls: list[dict] = []

    class ShortEnglishClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            calls.append(params)
            if _is_spanish_query(params):
                return _mock_response(200, _search_payload([{"key": "/works/ES0W"}]))
            # English pool exhausted after 3 docs: a short page is what used
            # to trigger the spanish backfill.
            return _mock_response(200, {"numFound": 3, "docs": [{"key": "/works/EN0W"}] * 3})

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", ShortEnglishClient):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    assert not any(_is_spanish_query(params) for params in calls)
    assert len(calls) == 1
    assert calls[0]["q"] == build_seed_query()
    assert calls[0]["limit"] == 10  # the whole slice is english when the quota is 0
    # A short page is the honest answer here: with no spanish stream to fill
    # from, there is nothing left to seed.
    assert [doc["key"] for doc in result] == ["/works/EN0W"] * 3


@pytest.mark.asyncio
async def test_get_popular_books_warns_when_the_filtered_pool_is_too_small(
    calibrated_thresholds, monkeypatch
):
    """A pool below SEED_TOP_N_BOOKS must warn instead of stalling silently.

    Past the last result OL answers 200 with an empty docs list, which the
    sync job reads as end-of-listing and wraps its cursor to 0 — the same
    silent failure /trending/weekly.json had (feature 25). The thresholds are
    env-tunable, so this is reachable by configuration.
    """
    monkeypatch.setattr(settings, "SEED_TOP_N_BOOKS", 100)

    class SmallPoolClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            docs = [{"key": f"/works/OL{i}W"} for i in range(params["limit"])]
            return _mock_response(200, {"numFound": 5, "docs": docs})

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", SmallPoolClient):
        with patch.object(ol_adapter.logger, "warning") as mock_warning:
            client = OpenLibraryClient()
            await client.get_popular_books(limit=10)

    assert any(
        "smaller than SEED_TOP_N_BOOKS" in call.args[0] for call in mock_warning.call_args_list
    )


@pytest.mark.asyncio
async def test_get_popular_books_does_not_warn_when_the_pool_is_large_enough(
    calibrated_thresholds, monkeypatch
):
    """The pool guard stays quiet when both streams together cover the target."""
    monkeypatch.setattr(settings, "SEED_TOP_N_BOOKS", 100)

    class LargePoolClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            docs = [{"key": f"/works/OL{i}W"} for i in range(params["limit"])]
            return _mock_response(200, {"numFound": 16959, "docs": docs})

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", LargePoolClient):
        with patch.object(ol_adapter.logger, "warning") as mock_warning:
            client = OpenLibraryClient()
            await client.get_popular_books(limit=10)

    assert not any(
        "smaller than SEED_TOP_N_BOOKS" in call.args[0] for call in mock_warning.call_args_list
    )


def test_search_fields_keep_the_classification_and_add_edition_count():
    """ddc/lcc must survive the filter rewrite; edition_count must be requested.

    ddc/lcc stopped being a *filter* in feature 73 but they are still what
    feature 72 derives genres from, so dropping them from the field set would
    silently strip every seeded book of its genres. edition_count is the new
    discriminant and is requested (Solr filters fine without returning it) so
    a page can be audited against the threshold that selected it — which also
    makes it a field the hand-built search_doc in scheduler/jobs.py has to
    know about (Issue #17).
    """
    fields = _OL_SEARCH_FIELDS.split(",")

    assert "ddc" in fields
    assert "lcc" in fields
    assert "subject_facet" in fields
    assert "edition_count" in fields


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ({"key": "/works/OL82563W"}, True),
        ({"key": "/works/OL9394106M"}, False),
        ({"key": ""}, False),
        ({}, False),
        ({"key": None}, False),
    ],
)
def test_is_work_doc_only_accepts_work_keys(doc, expected):
    """search.json returns the odd orphan *edition* key dressed up as a work.

    ``/works/OL9394106M`` ("Metal Gear Solid Volume 1") is an edition with no
    parent work: the M suffix gives it away. Persisting it would create a
    catalog entry whose work detail lookup resolves to an edition endpoint.
    """
    assert _is_work_doc(doc) is expected


@pytest.mark.asyncio
async def test_get_popular_books_drops_orphan_edition_keys_and_tops_up(calibrated_thresholds):
    """A dropped non-work key is replaced by the next doc, not left as a gap.

    This is why the filter lives inside ``_fetch_seed_stream``'s pagination
    loop instead of in ``get_popular_books``: dropping docs after the slot
    budget has been split would return a short page with *neither* stream
    exhausted, and the sync job reads a short page as end-of-listing and wraps
    its cursor back to 0.
    """
    en_pool = [{"key": f"/works/EN{i}W"} for i in range(20)]
    en_pool[3] = {"key": "/works/OL9394106M"}  # orphan edition key
    calls: list[dict] = []

    class OrphanKeyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            calls.append(params)
            if _is_spanish_query(params):
                return _mock_response(200, {"numFound": 1858, "docs": [{"key": "/works/ES0W"}]})
            start = params["offset"]
            docs = en_pool[start : start + params["limit"]]
            return _mock_response(200, {"numFound": len(en_pool), "docs": docs})

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", OrphanKeyClient):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    # Full page, no orphan key, no gap in the english sequence.
    assert len(result) == 10
    assert all(_is_work_doc(doc) for doc in result)
    assert [doc["key"] for doc in result] == [
        "/works/EN0W",
        "/works/EN1W",
        "/works/EN2W",
        "/works/EN4W",
        "/works/EN5W",
        "/works/EN6W",
        "/works/EN7W",
        "/works/EN8W",
        "/works/EN9W",
        "/works/ES0W",
    ]
    # The top-up asks for exactly the one missing doc, continuing the *raw*
    # API offset (9, the page size asked for) — mixing filtered and raw
    # counters here would either skip or re-request a document.
    english_calls = [call for call in calls if not _is_spanish_query(call)]
    assert len(english_calls) == 2
    assert english_calls[0]["offset"] == 0
    assert english_calls[0]["limit"] == 9
    assert english_calls[1]["offset"] == 9
    assert english_calls[1]["limit"] == 1


@pytest.mark.asyncio
async def test_get_popular_books_page_is_short_when_the_drop_empties_an_exhausted_stream(
    calibrated_thresholds, monkeypatch
):
    """With the pool genuinely exhausted, the dropped doc makes the page shorter.

    The loop must stop instead of paginating forever looking for a
    replacement that does not exist: OL answers a past-the-end page with
    fewer docs than requested, and that — not the filtered count — is the
    end-of-results signal. A short page here is the honest answer.
    """
    monkeypatch.setattr(settings, "SEED_TOP_N_BOOKS", 1)
    en_pool = [
        {"key": "/works/EN0W"},
        {"key": "/works/EN1W"},
        {"key": "/works/OL9394106M"},
        {"key": "/works/EN3W"},
        {"key": "/works/EN4W"},
    ]
    calls: list[dict] = []

    class ExhaustedPoolClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            calls.append(params)
            if _is_spanish_query(params):
                return _mock_response(200, {"numFound": 0, "docs": []})
            start = params["offset"]
            docs = en_pool[start : start + params["limit"]]
            return _mock_response(200, {"numFound": len(en_pool), "docs": docs})

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", ExhaustedPoolClient):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    assert [doc["key"] for doc in result] == [
        "/works/EN0W",
        "/works/EN1W",
        "/works/EN3W",
        "/works/EN4W",
    ]
    # One english page (short -> end of results) plus one empty spanish page:
    # the drop must not trigger extra requests once the stream is exhausted.
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_backfill_resumes_from_the_raw_offset_after_a_dropped_key(calibrated_thresholds):
    """The exhaustion backfill must resume from the raw API offset, not a filtered one.

    Regression for the round-3 review blocker. ``_fetch_seed_stream`` returns
    docs in *filtered* space, so ``en_offset + len(en_docs)`` is short by one
    for every orphan key dropped: the backfill re-requested the last docs it
    had just returned and the page came back with a duplicate — 10 items, 9
    distinct, ``EN9W`` twice. Since the sync job upserts per item, the
    duplicate is silent: it inflates ``synced`` and seeds one fewer distinct
    book instead of failing.

    Setup is the reviewer's: one orphan inside the english slice plus an empty
    spanish stream, which is what forces the backfill to run.
    """
    en_pool = [{"key": f"/works/EN{i}W"} for i in range(40)]
    en_pool[1] = {"key": "/works/OL1M"}  # orphan edition key inside the slice
    calls: list[dict] = []

    class OrphanPlusEmptySpanishClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            calls.append(params)
            if _is_spanish_query(params):
                return _mock_response(200, {"numFound": 0, "docs": []})
            start = params["offset"]
            docs = en_pool[start : start + params["limit"]]
            return _mock_response(200, {"numFound": len(en_pool), "docs": docs})

    with patch(
        "backlogg.books.adapters.open_library.httpx.AsyncClient", OrphanPlusEmptySpanishClient
    ):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    keys = [doc["key"] for doc in result]
    assert len(keys) == 10
    assert len(set(keys)) == 10  # the bug produced EN9W twice
    assert keys == [f"/works/EN{i}W" for i in [0, 2, 3, 4, 5, 6, 7, 8, 9, 10]]

    # Asserted on the wire, not just on the docs: the top-up of the dropped
    # key stops the english stream at raw offset 10, and the backfill for the
    # empty spanish slot must continue from there — not from 9, which is where
    # filtered arithmetic would have pointed.
    english_calls = [
        (call["offset"], call["limit"]) for call in calls if not _is_spanish_query(call)
    ]
    assert english_calls == [(0, 9), (9, 1), (10, 1)]


@pytest.mark.asyncio
async def test_get_popular_books_keeps_paginating_when_a_whole_page_is_dropped(
    calibrated_thresholds,
):
    """A page made entirely of orphan keys is not read as end-of-results.

    ``len(docs) < per_page`` is evaluated on the raw page precisely so that a
    full page of unusable docs keeps the cursor moving instead of stalling.
    """
    calls: list[dict] = []

    class AllOrphansFirstPageClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            calls.append(params)
            if _is_spanish_query(params):
                return _mock_response(200, {"numFound": 1858, "docs": [{"key": "/works/ES0W"}]})
            if params["offset"] == 0:
                docs = [{"key": f"/works/OL{i}M"} for i in range(params["limit"])]
            else:
                docs = [
                    {"key": f"/works/EN{params['offset'] + i}W"} for i in range(params["limit"])
                ]
            return _mock_response(200, {"numFound": 16959, "docs": docs})

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", AllOrphansFirstPageClient):
        client = OpenLibraryClient()
        result = await client.get_popular_books(limit=10)

    assert len(result) == 10
    assert all(_is_work_doc(doc) for doc in result)
    english_calls = [call for call in calls if not _is_spanish_query(call)]
    assert [call["offset"] for call in english_calls] == [0, 9]
    assert [call["limit"] for call in english_calls] == [9, 9]


# ---------------------------------------------------------------------------
# search_book — page/limit and retry (Issue #14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_book_returns_full_docs_list():
    """search_book returns the whole page of docs, not just the top hit (Issue #14)."""
    fake_docs = [
        {"key": "/works/OL1W", "title": "Dune"},
        {"key": "/works/OL2W", "title": "Dune Messiah"},
    ]
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            captured["params"] = params
            return _mock_response(200, _search_payload(fake_docs))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        result = await client.search_book("dune", page=1, limit=20)

    assert result == fake_docs
    assert captured["params"]["limit"] == 20
    assert captured["params"]["page"] == 1


@pytest.mark.asyncio
async def test_search_book_returns_empty_list_when_no_matches():
    """search_book returns [] (not None) when Open Library has no matches."""

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            return _mock_response(200, _search_payload([]))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        result = await client.search_book("xxxxxxxxxxxxxxxxxxx_no_match")

    assert result == []


@pytest.mark.asyncio
async def test_search_book_defaults_to_top_hit_only():
    """The on-demand fallback default (limit=1) is preserved for backward compatibility."""
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            captured["params"] = params
            return _mock_response(200, _search_payload([{"key": "/works/OL1W"}]))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        await client.search_book("dune")

    assert captured["params"]["limit"] == 1
    assert captured["params"]["page"] == 1


@pytest.mark.asyncio
async def test_search_book_retries_5xx_and_succeeds_on_second_attempt():
    """search_book is retried via _ol_search_retry on transient 5xx responses."""
    fake_docs = [{"key": "/works/OL1W", "title": "Dune"}]
    call_count = 0

    class FlakyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_response(500)
            return _mock_response(200, _search_payload(fake_docs))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FlakyClient):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            client = OpenLibraryClient()
            result = await client.search_book("dune")

    assert result == fake_docs
    assert call_count == 2
    mock_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_book_raises_on_403_without_retry():
    """A 4xx must raise immediately — no retry, no [] masking."""
    call_count = 0

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            return _mock_response(403)

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.search_book("dune")

    assert call_count == 1


# ---------------------------------------------------------------------------
# get_author retry tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_author_returns_none_after_three_timeouts():
    """get_author must return None (not raise) after 3 consecutive TimeoutExceptions."""
    call_count = 0

    class TimeoutClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectTimeout("timed out")

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", TimeoutClient):
        with patch("backlogg.books.adapters.open_library.asyncio.sleep", AsyncMock()):
            ol = OpenLibraryClient()
            result = await ol.get_author("OL123A")

    assert result is None
    assert call_count == 3


@pytest.mark.asyncio
async def test_get_author_succeeds_on_retry_after_timeout():
    """get_author must return data when a retry succeeds after an initial timeout."""
    attempts = 0
    author_data = {"key": "/authors/OL123A", "name": "Test Author"}

    class FlakyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectTimeout("first attempt fails")
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=author_data)
            resp.raise_for_status = MagicMock()
            return resp

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", FlakyClient):
        with patch("backlogg.books.adapters.open_library.asyncio.sleep", AsyncMock()):
            ol = OpenLibraryClient()
            result = await ol.get_author("OL123A")

    assert result == author_data
    assert attempts == 2


@pytest.mark.asyncio
async def test_get_author_returns_none_on_404():
    """get_author must return None when the API returns 404."""

    class NotFoundClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            resp = MagicMock()
            resp.status_code = 404
            return resp

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", NotFoundClient):
        ol = OpenLibraryClient()
        result = await ol.get_author("OL999A")

    assert result is None


# ---------------------------------------------------------------------------
# Classification tests (feature 72 — lcc/ddc/subject_facet -> controlled genres)
# ---------------------------------------------------------------------------


def _genre_slugs(search_doc: dict) -> list[str]:
    """Run book_to_dict over *search_doc* and return the derived genre slugs."""
    result = OpenLibraryClient().book_to_dict(search_doc)
    return [g["slug"] for g in result["genres"]]


def test_derive_genres_lcc_literature_is_refined_by_ddc_literary_form():
    """Inside the literature classes, ddc adds the form lcc cannot express.

    LCC files literature by provenance and language (PS American literature,
    PR English literature) and never encodes form, so the literary-form digit
    of the 8xx ddc number is read *in addition* and prepended. The discipline
    still comes from lcc; ddc only refines it.
    """
    # 8_3 -> fiction (both the plain and the segmented "813/.54" spelling)
    assert _genre_slugs(
        {
            "title": "American Novel",
            "first_publish_year": 1998,
            "lcc": ["PS-3568.00000000.O243 D3 1998"],
            "ddc": ["813.54", "813/.54"],
        }
    ) == ["fiction", "literature"]
    assert _genre_slugs(
        {
            "title": "English Novel",
            "lcc": ["PR-6068.00000000.O93 H377 1997"],
            "ddc": ["823.914"],
        }
    ) == ["fiction", "literature"]
    # 8_4 -> essays
    assert _genre_slugs(
        {
            "title": "American Essays",
            "lcc": ["PS-3568.00000000.O243 E8"],
            "ddc": ["814.54"],
        }
    ) == ["essays", "literature"]
    # 8_1 -> poetry
    assert _genre_slugs(
        {
            "title": "American Poems",
            "lcc": ["PS-3568.00000000.O243 P6"],
            "ddc": ["811.54"],
        }
    ) == ["poetry", "literature"]
    # 8_2 -> drama
    assert _genre_slugs(
        {
            "title": "English Plays",
            "lcc": ["PR-2823.00000000.A2 M67"],
            "ddc": ["822.33"],
        }
    ) == ["drama", "literature"]


def test_derive_genres_lcc_literature_without_ddc_stays_plain_literature():
    """No ddc means no form signal — "Literature" is the honest answer."""
    assert _genre_slugs(
        {
            "title": "No Ddc",
            "first_publish_year": 1998,
            "lcc": ["PS-3568.00000000.O243 D3 1998"],
        }
    ) == ["literature"]
    # Same when ddc is present but carries no usable form digit: 818 is
    # miscellaneous writings and 80x is theory/general.
    assert _genre_slugs({"title": "Miscellany", "lcc": ["PS-3568"], "ddc": ["818.5403"]}) == [
        "literature"
    ]
    assert _genre_slugs({"title": "Criticism", "lcc": ["PR-0021"], "ddc": ["801.95"]}) == [
        "literature"
    ]
    # And when ddc is not a literature number at all, it is simply ignored.
    assert _genre_slugs({"title": "Odd Pair", "lcc": ["PR-0021"], "ddc": ["302.23"]}) == [
        "literature"
    ]


def test_derive_genres_lcc_pz_with_ddc_fiction_does_not_duplicate():
    """PZ already carries "fiction"; the ddc refinement must not duplicate it.

    PZ does not resolve to "literature", so the refinement never fires — and
    even if it did, the dedup by slug keeps the output clean.
    """
    assert _genre_slugs(
        {
            "title": "Juvenile Novel",
            "lcc": ["PZ-0007.00000000.R79835 Ha 1998"],
            "ddc": ["823.914"],
        }
    ) == ["fiction", "childrens-young-adult"]


def test_derive_genres_non_literature_lcc_ignores_ddc_literary_form():
    """Outside the literature classes lcc rules alone — ddc never refines.

    Both taxonomies classify by discipline there, so mixing them would only
    produce contradictory or near-duplicate labels.
    """
    # A mathematics book mis-shelved with a fiction ddc stays mathematics
    assert _genre_slugs(
        {"title": "Algorithms", "lcc": ["QA-0076.00000000.73"], "ddc": ["813.54"]}
    ) == ["mathematics"]
    assert _genre_slugs({"title": "Habits", "lcc": ["BF-0637.00000000.C6"], "ddc": ["158.1"]}) == [
        "psychology"
    ]
    assert _genre_slugs({"title": "Cookbook", "lcc": ["TX-0714"], "ddc": ["811.54"]}) == ["cooking"]


def test_derive_genres_from_lcc_only():
    """A work with only lcc is classified from its letter class."""
    assert _genre_slugs({"title": "Psych Only", "lcc": ["BF-0637.00000000.C6 C368 2018"]}) == [
        "psychology"
    ]
    # Two-letter prefix wins over the one-letter fallback (HD -> economics,
    # not H -> social sciences)
    assert _genre_slugs({"title": "Econ", "lcc": ["HD-0057.00000000.7 K563 2016"]}) == [
        "economics-business"
    ]
    # One-letter fallback when the two-letter prefix is unmapped
    assert _genre_slugs({"title": "History", "lcc": ["DA-0566.00000000.9 C5"]}) == ["history"]


def test_derive_genres_from_lcc_pz_is_fiction_and_juvenile():
    """PZ (fiction and juvenile belles lettres) yields both labels."""
    assert _genre_slugs({"title": "Juvenile", "lcc": ["PZ-0007.00000000.R79835 Ha 1998"]}) == [
        "fiction",
        "childrens-young-adult",
    ]


def test_derive_genres_multivalued_lcc_uses_the_dominant_class():
    """A mixed lcc list resolves to its most frequent class, not their union.

    Open Library contributes one lcc entry per edition, so the list is
    routinely multivalued and mixed (51% of the works that carry lcc in the
    100 most-shelved sample carry more than one class). Aggregating every
    class let a single oddly shelved edition speak for the whole work.
    Both cases below are real records.
    """
    # L'étranger: 40 entries of PQ (French literature) and 2 of PZ from a
    # school edition. The 2 must not turn Camus into children's literature.
    letranger = ["PQ-2605.00000000.A3734 E8 1957"] * 40 + [
        "PZ-0003.00000000.C1468 St",
        "PZ-0003.00000000.C1468 Str",
    ]
    assert _genre_slugs({"title": "L'étranger", "lcc": letranger}) == ["literature"]

    # The Shining: 11 PS (American literature) against 3 PZ, with ddc 813.54
    # supplying the literary form on top of the dominant class.
    shining = ["PS-3561.00000000.I483 S5 1977"] * 11 + ["PZ-0004.00000000.K5227 Sh"] * 3
    assert _genre_slugs({"title": "The Shining", "lcc": shining, "ddc": ["813.54"]}) == [
        "fiction",
        "literature",
    ]

    # The minority class contributes nothing at all, not even a trailing label
    assert _genre_slugs(
        {
            "title": "Mostly Psychology",
            "lcc": ["BF-0637.00000000.C6", "BF-0637.00000000.S4", "BF-0121", "TX-0714"],
        }
    ) == ["psychology"]


def test_derive_genres_multivalued_lcc_tie_goes_to_first_appearance():
    """A tie is broken by first appearance in the list — deterministic and stable.

    Reversing the list therefore hands the win to the other class, which is
    the documented rule rather than an accident of set/dict iteration order.
    """
    assert _genre_slugs(
        {"title": "Tie", "lcc": ["QA-0076.00000000.73", "PS-3568"], "ddc": ["813.54"]}
    ) == ["mathematics"]
    assert _genre_slugs(
        {"title": "Tie Reversed", "lcc": ["PS-3568", "QA-0076.00000000.73"], "ddc": ["813.54"]}
    ) == ["fiction", "literature"]

    # Same input, repeated calls: always the same answer
    doc = {"title": "Stable", "lcc": ["TX-0714", "BF-0637", "M-1630", "QA-0076"]}
    assert [_genre_slugs(doc) for _ in range(5)] == [["cooking"]] * 5


def test_derive_genres_lcc_pz1_to_pz4_is_adult_fiction():
    """PZ1-PZ4 is fiction in English for adults — never children's & YA.

    An older LCC practice, still all over Open Library's records: The Shining
    carries PZ4 and L'étranger PZ3.
    """
    assert _genre_slugs({"title": "Pz4", "lcc": ["PZ-0004.00000000.K5227 Sh"]}) == ["fiction"]
    assert _genre_slugs({"title": "Pz3", "lcc": ["PZ-0003.00000000.C1468 St"]}) == ["fiction"]
    assert _genre_slugs({"title": "Pz1", "lcc": ["PZ-0001.00000000.A1"]}) == ["fiction"]


def test_derive_genres_lcc_pz5_and_above_is_childrens_and_young_adult():
    """PZ5-PZ10.3 is juvenile belles lettres — this half really is children's/YA.

    The last two assertions pin the exact cut at 5.0, the number that separates
    adult fiction from juvenile and the whole point of the subdivision.
    """
    # PZ7, juvenile fiction (Harry Potter, The Fault in Our Stars)
    assert _genre_slugs({"title": "Pz7", "lcc": ["PZ-0007.00000000.R79835 Har 1998"]}) == [
        "fiction",
        "childrens-young-adult",
    ]
    # PZ10.3, normalized by OL with the decimals in the second position
    assert _genre_slugs({"title": "Pz10.3", "lcc": ["PZ-0010.73100000.B4514 Fr"]}) == [
        "fiction",
        "childrens-young-adult",
    ]
    # Unnormalized spelling ("PZ7.R79835") reads the same number
    assert _genre_slugs({"title": "Pz7 Raw", "lcc": ["PZ7.R79835 Har 1998"]}) == [
        "fiction",
        "childrens-young-adult",
    ]
    # The boundary pair. PZ4.9 is the largest adult number, PZ5.0 the smallest
    # juvenile one, so this is what makes `>= _LCC_PZ_JUVENILE_MIN` fail as `>`.
    assert _genre_slugs({"title": "Pz4.9", "lcc": ["PZ-0004.90000000.A1"]}) == ["fiction"]
    assert _genre_slugs({"title": "Pz5", "lcc": ["PZ-0005.00000000.A1"]}) == [
        "fiction",
        "childrens-young-adult",
    ]


def test_derive_genres_lcc_pz_without_a_readable_number_is_only_fiction():
    """An unreadable PZ number falls back to plain Fiction, the safe assertion.

    "Fiction" is what the whole PZ class shares; inferring "children's" from a
    number that could not be parsed is the more damaging of the two possible
    errors and is exactly the bug this round fixes.
    """
    assert _genre_slugs({"title": "Bare", "lcc": ["PZ"]}) == ["fiction"]
    assert _genre_slugs({"title": "No Number", "lcc": ["PZ-K5227 Sh"]}) == ["fiction"]
    assert _genre_slugs({"title": "Junk Number", "lcc": ["PZ-.-. x"]}) == ["fiction"]


def test_derive_genres_literary_form_refines_the_dominant_class_only():
    """The ddc refinement keys off the dominant class, never a secondary one.

    A mathematics book with one stray PS edition used to come out as
    "Fiction" because "literature" was present in the aggregated list.
    """
    assert _genre_slugs(
        {
            "title": "Algorithms With A Stray Ps",
            "lcc": ["QA-0076.00000000.73", "QA-0076.00000000.9", "PS-3568"],
            "ddc": ["813.54"],
        }
    ) == ["mathematics"]
    # And it does still fire when literature *is* the dominant class
    assert _genre_slugs(
        {
            "title": "Novel With A Stray Qa",
            "lcc": ["PS-3568.00000000.O243", "PS-3568.00000000.O244", "QA-0076"],
            "ddc": ["813.54"],
        }
    ) == ["fiction", "literature"]


def test_derive_genres_from_ddc_only_literary_form_is_fiction():
    """8_3 is the fiction literary form: 813.54 -> Fiction + Literature."""
    assert _genre_slugs({"title": "Ddc Fiction", "ddc": ["813/.54"]}) == ["fiction", "literature"]


def test_derive_genres_from_ddc_only_other_literary_forms():
    """The other 8xx form digits map to poetry, drama and essays."""
    assert _genre_slugs({"title": "Poems", "ddc": ["811.54"]}) == ["poetry", "literature"]
    assert _genre_slugs({"title": "Plays", "ddc": ["822.33"]}) == ["drama", "literature"]
    assert _genre_slugs({"title": "Essays", "ddc": ["824.912"]}) == ["essays", "literature"]
    # 80x is literature theory/general — no form digit to read
    assert _genre_slugs({"title": "Theory", "ddc": ["801.95"]}) == ["literature"]


def test_derive_genres_from_ddc_non_literature_classes_and_refinements():
    """Centuries map by hundreds, with the documented refinements on top."""
    assert _genre_slugs({"title": "Programming", "ddc": ["005.133"]}) == ["computing"]
    assert _genre_slugs({"title": "Self Help", "ddc": ["158.1"]}) == ["self-help"]
    assert _genre_slugs({"title": "Psychology", "ddc": ["153.4"]}) == ["psychology"]
    assert _genre_slugs({"title": "Cookbook", "ddc": ["641.5"]}) == ["cooking"]
    assert _genre_slugs({"title": "Athletics", "ddc": ["796.332"]}) == ["sports-recreation"]
    assert _genre_slugs({"title": "A Life", "ddc": ["920"]}) == ["biography"]
    assert _genre_slugs({"title": "A Life", "ddc": ["92"]}) == ["biography"]
    # 929 is genealogy/names/heraldry, not biography: the 3-digit prefix must
    # win over the abridged "92" biography notation
    assert _genre_slugs({"title": "Heraldry", "ddc": ["929.6"]}) == ["history"]
    assert _genre_slugs({"title": "Genealogy", "ddc": ["929"]}) == ["history"]
    assert _genre_slugs({"title": "Symphonies", "ddc": ["780.9"]}) == ["music"]
    assert _genre_slugs({"title": "Travels", "ddc": ["914.204"]}) == ["geography-travel"]
    assert _genre_slugs({"title": "Religion", "ddc": ["230"]}) == ["religion"]
    assert _genre_slugs({"title": "War", "ddc": ["940.5318"]}) == ["history"]


def test_derive_genres_falls_back_to_filtered_subject_facet():
    """With neither lcc nor ddc, subject_facet is filtered by the vocabulary."""
    slugs = _genre_slugs(
        {
            "title": "Facet Only",
            "subject_facet": [
                "Concentration camps",  # folksonomy noise -> dropped
                "Country homes",  # folksonomy noise -> dropped
                "Biography",  # controlled -> kept
                "History",  # controlled -> kept
            ],
        }
    )
    assert slugs == ["biography", "history"]


def test_derive_genres_ignores_subject_facet_when_lcc_present():
    """subject_facet is a last resort, never merged with a real classification."""
    assert _genre_slugs(
        {
            "title": "Facet Ignored",
            "lcc": ["QA-0076.00000000.73"],
            "subject_facet": ["Cooking", "Travel"],
        }
    ) == ["mathematics"]


def test_derive_genres_returns_empty_when_nothing_matches():
    """No classification and unmatched facets means no genres — not junk labels."""
    assert _genre_slugs({"title": "Unclassifiable", "first_publish_year": 1990}) == []
    assert (
        _genre_slugs(
            {
                "title": "Noise Only",
                "subject_facet": ["Triathlon", "Concentration camps", "Country homes"],
            }
        )
        == []
    )
    assert _genre_slugs({"title": "Empty Lists", "lcc": [], "ddc": [], "subject_facet": []}) == []


def test_derive_genres_survives_malformed_classification_values():
    """Malformed or unexpected lcc/ddc payloads must never raise."""
    doc = {
        "title": "Malformed",
        "lcc": ["", "1234-5678", "  ", "YY-0001", None, 42, "?!"],
        "ddc": ["", "n/a", "[Fic]", None, 7],
        "subject_facet": "Fiction",  # a bare string instead of a list
    }
    slugs = _genre_slugs(doc)
    # "YY" is not an LCC class, so nothing matches and ddc's "[Fic]" answers
    assert slugs == ["fiction"]

    # A doc where every field is the wrong type still classifies to nothing
    assert (
        _genre_slugs({"title": "Junk Types", "lcc": 5, "ddc": {"a": 1}, "subject_facet": 9}) == []
    )


def test_derive_genres_only_emits_controlled_vocabulary():
    """Every persisted label comes from the closed vocabulary."""
    result = OpenLibraryClient().book_to_dict(
        {"title": "Vocab Check", "lcc": ["PZ-0007.00000000.R79835"]}
    )
    for genre in result["genres"]:
        assert genre["slug"] in _CONTROLLED_GENRES
        assert genre["name"] == _CONTROLLED_GENRES[genre["slug"]]


def test_mapping_tables_only_reference_controlled_vocabulary():
    """Every slug any mapping table can emit must exist in _CONTROLLED_GENRES.

    The precedence in _derive_genres filters each source against the closed
    vocabulary *before* deciding whether it answered, so a typo'd slug in a
    table degrades that source into the next one instead of leaving the book
    genre-less. This test makes the tables themselves the guard rail rather
    than relying on that fallback (and on human vigilance) — a typo fails
    here, loudly, instead of silently downgrading a whole LCC class.
    """
    tables = {
        "_LCC_CLASS_GENRES": _LCC_CLASS_GENRES,
        "_DDC_PREFIX_GENRES": _DDC_PREFIX_GENRES,
        "_DDC_LITERARY_FORM_GENRES": _DDC_LITERARY_FORM_GENRES,
        "_DDC_BRACKET_GENRES": _DDC_BRACKET_GENRES,
        "_SUBJECT_FACET_GENRES": _SUBJECT_FACET_GENRES,
        "_LCC_PZ_SUBDIVISION_GENRES": _LCC_PZ_SUBDIVISION_GENRES,
    }
    unknown = {
        f"{table_name}[{key!r}]": slug
        for table_name, table in tables.items()
        for key, slugs in table.items()
        for slug in slugs
        if slug not in _CONTROLLED_GENRES
    }
    assert unknown == {}, f"mapping tables emit slugs outside the vocabulary: {unknown}"


def test_book_to_dict_no_longer_reads_subject():
    """The folksonomic `subject` field is ignored entirely (feature 72)."""
    assert (
        _genre_slugs(
            {
                "title": "Subject Ignored",
                "subject": ["Fiction", "Fantasy", "Triathlon"],
            }
        )
        == []
    )


# ---------------------------------------------------------------------------
# get_work_detail redirect tests (Issue #10)
# ---------------------------------------------------------------------------

# Real Open Library edition payload shape for OL8796283M (one of the 4 IDs
# confirmed in production logs, Issue #10) — the work_id resolves to a
# standalone edition record, not a work.
_EDITION_PAYLOAD = {
    "key": "/books/OL8796283M",
    "title": "The Malleus Maleficarum of Heinrich Kramer and James Sprenger",
    "type": {"key": "/type/edition"},
    "authors": [{"key": "/authors/OL757974A"}, {"key": "/authors/OL4788297A"}],
    "publish_date": "February 2000",
    "subjects": ["History", "Religion"],
}

_WORK_PAYLOAD = {
    "key": "/works/OL27482W",
    "title": "The Hobbit",
    "type": {"key": "/type/work"},
    "authors": [{"author": {"key": "/authors/OL26320A"}, "type": {"key": "/type/author_role"}}],
    "description": "A tale of high adventure.",
}


@pytest.mark.asyncio
async def test_get_work_detail_enables_follow_redirects():
    """get_work_detail's AsyncClient must be constructed with follow_redirects=True."""
    captured_kwargs: dict = {}

    class CapturingClient:
        def __init__(self, **kwargs):
            nonlocal captured_kwargs
            captured_kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return _mock_response(200, dict(_WORK_PAYLOAD))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", CapturingClient):
        client = OpenLibraryClient()
        await client.get_work_detail("OL27482W")

    assert captured_kwargs.get("follow_redirects") is True


@pytest.mark.asyncio
async def test_get_work_detail_follows_redirect_and_normalizes_edition_authors():
    """A work_id that OL redirects to /books/{id}.json (Issue #10) must not raise.

    Reproduces the real production traceback: OL responds to
    GET /works/OL8796283M.json with a 301 to /books/OL8796283M.json. With
    follow_redirects=True the underlying httpx client transparently follows
    it, so client.get() returns the final edition response directly — this
    is what the fake client below simulates. The returned dict must be
    normalized into work shape so authors are not lost.
    """

    class RedirectingClient:
        def __init__(self, **kwargs):
            self.follow_redirects = kwargs.get("follow_redirects", False)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            assert url.endswith("/works/OL8796283M.json")
            assert self.follow_redirects is True  # the fix under test
            # Simulates httpx transparently following the 301 to /books/...
            return _mock_response(200, dict(_EDITION_PAYLOAD))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", RedirectingClient):
        client = OpenLibraryClient()
        result = await client.get_work_detail("OL8796283M")

    assert result is not None
    # Authors normalized from edition's flat shape to work's nested shape
    assert result["authors"] == [
        {"author": {"key": "/authors/OL757974A"}},
        {"author": {"key": "/authors/OL4788297A"}},
    ]
    # publish_date backfilled into first_publish_date since the edition has none
    assert result["first_publish_date"] == "February 2000"


@pytest.mark.asyncio
async def test_get_work_detail_returns_work_response_unmodified():
    """A genuine work response (no redirect involved) must pass through untouched."""

    class WorkClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return _mock_response(200, dict(_WORK_PAYLOAD))

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", WorkClient):
        client = OpenLibraryClient()
        result = await client.get_work_detail("OL27482W")

    assert result["authors"] == _WORK_PAYLOAD["authors"]
    assert result["description"] == _WORK_PAYLOAD["description"]
    assert "first_publish_date" not in result


@pytest.mark.asyncio
async def test_get_work_detail_returns_none_on_404():
    """get_work_detail must return None when the API responds 404."""

    class NotFoundClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            resp = MagicMock()
            resp.status_code = 404
            return resp

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", NotFoundClient):
        client = OpenLibraryClient()
        result = await client.get_work_detail("OL999999W")

    assert result is None


@pytest.mark.asyncio
async def test_get_author_enables_follow_redirects():
    """get_author's AsyncClient must also be constructed with follow_redirects=True."""
    captured_kwargs: dict = {}

    class CapturingClient:
        def __init__(self, **kwargs):
            nonlocal captured_kwargs
            captured_kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return _mock_response(200, {"key": "/authors/OL123A", "name": "Test Author"})

    with patch("backlogg.books.adapters.open_library.httpx.AsyncClient", CapturingClient):
        client = OpenLibraryClient()
        await client.get_author("OL123A")

    assert captured_kwargs.get("follow_redirects") is True


@pytest.mark.asyncio
async def test_persist_book_authors_handles_normalized_edition_authors():
    """The normalized edition detail from get_work_detail must persist without raising.

    Exercises the full path from Issue #10: a work_detail dict shaped like
    get_work_detail's normalized edition output flows into
    _persist_book_authors (backlogg/books/service.py) — the code that was
    silently losing authors (people_errors) before this fix — and must
    reach upsert_credit for both authors without an exception escaping.
    """
    book = MagicMock()
    book.id = 42
    db = AsyncMock()

    edition_shaped_work_detail = {
        "authors": [
            {"author": {"key": "/authors/OL757974A"}},
            {"author": {"key": "/authors/OL4788297A"}},
        ],
    }

    author_payloads = {
        "OL757974A": {"key": "/authors/OL757974A", "name": "Heinrich Kramer"},
        "OL4788297A": {"key": "/authors/OL4788297A", "name": "James Sprenger"},
    }

    with (
        patch(
            "backlogg.books.service._ol_client.get_author",
            AsyncMock(side_effect=lambda author_id: author_payloads[author_id]),
        ),
        patch(
            "backlogg.books.service.people_repo.get_person_id_by_external",
            AsyncMock(return_value=None),
        ),
        patch(
            "backlogg.books.service.people_repo.upsert_person",
            AsyncMock(side_effect=lambda db, data: MagicMock(id=hash(data["slug"]) % 1000)),
        ),
        patch("backlogg.books.service.upsert_external_id", AsyncMock()),
        patch(
            "backlogg.books.service.people_repo.upsert_credit", AsyncMock()
        ) as mock_upsert_credit,
    ):
        await _persist_book_authors(db, book, edition_shaped_work_detail)

    assert mock_upsert_credit.await_count == 2
    persisted_roles = {call.args[1]["role"] for call in mock_upsert_credit.await_args_list}
    assert persisted_roles == {"AUTHOR"}


# ---------------------------------------------------------------------------
# isbn tests (feature 71 — book_isbn_field)
# ---------------------------------------------------------------------------


def test_book_to_dict_maps_first_isbn_from_search_doc():
    """book_to_dict must persist the first ISBN when search.json returns several."""
    ol = OpenLibraryClient()
    search_doc = {
        "title": "Dune",
        "first_publish_year": 1965,
        "isbn": ["9780441013593", "0441013597", "9780450011849"],
    }
    result = ol.book_to_dict(search_doc)
    assert result["isbn"] == "9780441013593"


def test_book_to_dict_isbn_is_none_when_absent():
    """book_to_dict must not break and must return isbn=None when search_doc has none."""
    ol = OpenLibraryClient()
    search_doc = {
        "title": "Untitled Work",
        "first_publish_year": 2020,
    }
    result = ol.book_to_dict(search_doc)
    assert result["isbn"] is None


def test_book_to_dict_isbn_is_none_when_empty_list():
    """An empty isbn list (present but no editions carry one) must also map to None."""
    ol = OpenLibraryClient()
    search_doc = {
        "title": "Another Untitled Work",
        "first_publish_year": 2021,
        "isbn": [],
    }
    result = ol.book_to_dict(search_doc)
    assert result["isbn"] is None


def test_book_to_dict_caps_genres_at_five():
    """book_to_dict must return at most 5 genres even when more classes match.

    The cap is only reachable through the multivalued ddc path: the lcc path
    emits the dominant class alone (at most literary form + class = 3 slugs).
    """
    ol = OpenLibraryClient()
    # Six ddc notations resolving to six distinct vocabulary slugs
    search_doc = {
        "title": "Genre Rich Book",
        "first_publish_year": 2010,
        "ddc": [
            "005.133",  # computing
            "158.1",  # self-help
            "641.5",  # cooking
            "796.332",  # sports & recreation
            "780.9",  # music
            "230",  # religion
        ],
    }
    result = ol.book_to_dict(search_doc)
    assert len(result["genres"]) == 5
    assert [g["slug"] for g in result["genres"]] == [
        "computing",
        "self-help",
        "cooking",
        "sports-recreation",
        "music",
    ]


def test_book_to_dict_lcc_no_longer_aggregates_every_class():
    """Six lcc entries of six different classes are a six-way tie, not a union.

    Before the dominant-class rule this doc produced five labels from six
    unrelated classes. Now the tie-break (first appearance) picks one class
    and only its slugs are emitted.
    """
    ol = OpenLibraryClient()
    search_doc = {
        "title": "Genre Rich Book",
        "first_publish_year": 2010,
        "lcc": [
            "PZ-0007.00000000.R79835",  # fiction + children's & YA
            "BF-0637.00000000.C6",  # psychology
            "D-0000.00000000.1",  # history
            "QA-0076.00000000.73",  # mathematics
            "M-1630.00000000.18",  # music
            "TX-0714.00000000.0",  # cooking
        ],
    }
    result = ol.book_to_dict(search_doc)
    assert [g["slug"] for g in result["genres"]] == ["fiction", "childrens-young-adult"]
