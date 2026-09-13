"""Tests for the OpenLibraryClient adapter.

⚠️ The seed *search* is gone (issue #27).  The nightly book lane no longer
walks /search.json by offset — it refreshes the catalog rows with the oldest
last_synced_at — so ``get_popular_books`` and the whole two-stream machinery
around it (``build_seed_query``, the slot math, the orphan-key drop) were
deleted with their tests.  What selects the book catalog now lives entirely in
``backlogg/books/adapters/openlibrary_dump.py::select_language``; the seed
thresholds it reads are still asserted here, because they are still settings.

Covers:
- get_works_by_ids asks /search.json for a batch of work ids in a single
  request (uppercase OR, full /works/ keys, limit sized to the batch) and
  requests the field set book_to_dict consumes
- get_works_by_ids sends the User-Agent header, asks nothing when given no
  ids, and reports ids Open Library does not answer for by omission
- get_works_by_ids raises immediately (no retry) on a 403 and retries
  transient 5xx responses via tenacity
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


# ---------------------------------------------------------------------------
# Issue #27: batch re-read of the catalog by work id (the refresh rotation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_works_by_ids_queries_one_request_for_the_whole_batch():
    """One /search.json request per batch, with every id in a single key: clause.

    The uppercase ``OR`` and the full ``/works/{OLID}`` keys are load-bearing
    Solr syntax (lowercase ``or`` returns 0 hits), and ``limit`` has to be the
    batch size or the default page size would silently truncate it.
    """
    docs = [{"key": "/works/OL1W", "title": "Dune"}, {"key": "/works/OL2W", "title": "Emma"}]
    response = _mock_response(200, _search_payload(docs))

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response) as mock_get:
        client = OpenLibraryClient()
        result = await client.get_works_by_ids(["OL1W", "OL2W"])

    mock_get.assert_awaited_once()
    params = mock_get.call_args.kwargs["params"]
    assert params["q"] == "key:(/works/OL1W OR /works/OL2W)"
    assert params["fields"] == _OL_SEARCH_FIELDS
    assert params["limit"] == 2
    assert "sort" not in params  # a key lookup has nothing to rank
    assert result == docs


@pytest.mark.asyncio
async def test_get_works_by_ids_sends_the_user_agent_header():
    """The identified User-Agent is what buys the 3 req/s budget (issue #26)."""
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["headers"] = kwargs.get("headers")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            return _mock_response(200, _search_payload([]))

    with patch("httpx.AsyncClient", FakeClient):
        client = OpenLibraryClient()
        await client.get_works_by_ids(["OL1W"])

    assert captured["headers"] == _OL_HEADERS


@pytest.mark.asyncio
async def test_get_works_by_ids_makes_no_request_for_an_empty_batch():
    """No ids, no HTTP: an empty ``key:()`` would be a syntax error at Solr."""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        client = OpenLibraryClient()
        assert await client.get_works_by_ids([]) == []
        assert await client.get_works_by_ids(["", None]) == []

    mock_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_works_by_ids_omits_the_ids_open_library_does_not_know():
    """A merged/deleted work is simply absent from the answer — never a 404.

    That omission is the caller's "gone" signal (``sync_books`` logs it and
    keeps the row), so the adapter must not invent a placeholder for it.
    """
    response = _mock_response(200, _search_payload([{"key": "/works/OL1W", "title": "Dune"}]))

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        client = OpenLibraryClient()
        result = await client.get_works_by_ids(["OL1W", "OL404W"])

    assert [doc["key"] for doc in result] == ["/works/OL1W"]


@pytest.mark.asyncio
async def test_get_works_by_ids_raises_on_403_without_retry():
    """A 403 is a client error: retrying it only burns the rate budget."""
    response = _mock_response(403)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response) as mock_get:
        client = OpenLibraryClient()
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_works_by_ids(["OL1W"])

    assert mock_get.await_count == 1


@pytest.mark.asyncio
async def test_get_works_by_ids_retries_5xx_and_succeeds_on_a_later_attempt():
    """Open Library's Solr 500s intermittently; tenacity covers it (Issue #9)."""
    docs = [{"key": "/works/OL1W", "title": "Dune"}]
    responses = [_mock_response(500), _mock_response(200, _search_payload(docs))]

    with (
        patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=responses) as mock_get,
        patch("tenacity.nap.time.sleep"),
    ):
        client = OpenLibraryClient()
        result = await client.get_works_by_ids(["OL1W"])

    assert mock_get.await_count == 2
    assert result == docs


# ---------------------------------------------------------------------------
# Feature 73: books_seeding_quality_filter — the catalog thresholds
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


def test_seed_threshold_defaults_are_the_calibrated_values():
    """The shipped defaults must be the live-measured ones, ignoring any local .env.

    16.959 english + 1.858 spanish works.  There is no item-count setting to
    compare that against any more (issue #27 removed the last one): these
    thresholds *are* the definition of the book catalog.
    """
    defaults = Settings(_env_file=None)

    assert defaults.BOOKS_SEED_MIN_READINGLOG == 20
    assert defaults.BOOKS_SEED_MIN_READINGLOG_ES == 5
    assert defaults.BOOKS_SEED_MIN_PAGES == 100
    assert defaults.BOOKS_SEED_MIN_EDITIONS == 10
    assert defaults.BOOKS_SEED_MIN_EDITIONS_ES == 2


def test_spanish_edition_floor_keeps_the_two_edition_control(calibrated_thresholds):
    """BOOKS_SEED_MIN_EDITIONS_ES must stay at 2: Reina roja has exactly 2 editions.

    Raising it to 3 nearly halves the spanish pool (1.858 -> 976) and expels a
    control title that must be seeded, so the floor is pinned by a test rather
    than left to a reviewer to remember.
    """
    assert settings.BOOKS_SEED_MIN_EDITIONS_ES <= 2


def test_search_fields_keep_the_classification_and_add_edition_count():
    """ddc/lcc must survive the filter rewrite; edition_count must be requested.

    ddc/lcc stopped being a *filter* in feature 73 but they are still what
    feature 72 derives genres from, so dropping them from the field set would
    silently strip every book of its genres — including on the nightly
    refresh, which re-reads these very docs through ``get_works_by_ids``.
    edition_count is the catalog filter's discriminant and is requested so a
    doc can be audited against the threshold that let it in.
    """
    fields = _OL_SEARCH_FIELDS.split(",")

    assert "ddc" in fields
    assert "lcc" in fields
    assert "subject_facet" in fields
    assert "edition_count" in fields


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
        # The person's external-id link is written by people_repo since
        # feature 84 (get_or_create_person_by_external), so that is the
        # reference this test has to intercept.
        patch("backlogg.people.repository.upsert_external_id", AsyncMock()),
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
