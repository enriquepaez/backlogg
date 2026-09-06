"""Unit tests for the Open Library dump pipeline (feature 87).

Every dump line used here is a **real** line of the 2026-08-31 monthly dump,
read from ``tests/books/fixtures/openlibrary_dump/`` — see the README next to
those files.  Nothing in this module touches the network or the database: the
pipeline's aggregation functions take iterables of lines on purpose, and the
one test that does exercise the HTTP streaming does it against an
``httpx.MockTransport``.

Covered here: the parsers (including the escaped-JSON and 4-column reading-log
shapes), the per-work aggregation, the feature-73 selection rules, the
``search.json``-shaped doc handed to ``book_to_dict``, and authorship rows.
The comparison against what ``search.json`` produces for the same works lives
in ``test_openlibrary_dump_fixture.py``.
"""

import gzip
import json

import httpx
import pytest

from backlogg.books.adapters import openlibrary_dump as dump
from backlogg.core.config import settings
from tests.books import dump_fixtures as fx

# ── Line parsing ─────────────────────────────────────────────────────────────


def test_parse_dump_line_reads_escaped_json_with_quotes():
    """A real work line whose JSON carries \\uXXXX escapes and escaped quotes.

    This is the property that makes ``split("\\t", 4)`` safe on 12,59 GB of
    third-party text: because the JSON column is escaped it can never contain
    a raw tab or newline, so the 5-column split cannot be fooled by content.
    """
    line = fx.line_with(fx.work_lines(), "OL10458677W")
    parsed = dump.parse_dump_line(line)

    assert parsed is not None
    record_type, key, record = parsed
    assert record_type == "/type/work"
    assert key == "/works/OL10458677W"
    # The escapes decode, and the embedded quotes survive intact.
    assert '"Os Lusi' in record["title"]
    assert "ʹ" in record["title"]


@pytest.mark.parametrize(
    "line",
    [
        "",
        "/type/work\t/works/OL1W\t1\t2020-01-01",  # only four columns
        "/type/work\t/works/OL1W\t1\t2020-01-01\t{not json}",
        "/type/work\t/works/OL1W\t1\t2020-01-01\t[1, 2]",  # valid JSON, not a record
    ],
)
def test_parse_dump_line_rejects_unusable_lines(line):
    """One bad line must never abort a 35-minute pass."""
    assert dump.parse_dump_line(line) is None


def test_split_dump_line_defers_the_json():
    """The cheap split hands back the raw JSON so callers can skip parsing it."""
    line = fx.line_with(fx.work_lines(), "OL10458677W")
    split = dump.split_dump_line(line)

    assert split is not None
    assert split[1] == "/works/OL10458677W"
    assert split[2].startswith("{")


def test_parse_reading_log_line_reads_the_four_column_shape():
    """reading-log is NOT the 5-column TSV: it is work/edition/shelf/date."""
    lines = fx.reading_log_lines()
    assert dump.parse_reading_log_line(lines[0]) == lines[0].split("\t")[0].removeprefix("/works/")
    # ``\\N`` in the edition column (no edition recorded) is still a valid row,
    # and it is the common case: 54 of the fragment's 167 rows have no edition.
    without_edition = [line for line in lines if line.split("\t")[1] == "\\N"]
    assert without_edition
    assert all(dump.parse_reading_log_line(line) is not None for line in without_edition)


@pytest.mark.parametrize("line", ["", "not a key\tx\ty\tz", "/authors/OL1A\t\\N\tWant to Read\tx"])
def test_parse_reading_log_line_rejects_unusable_rows(line):
    assert dump.parse_reading_log_line(line) is None


# ── Pass 1: the whitelist ────────────────────────────────────────────────────


def test_count_reading_log_counts_all_four_shelves():
    """``readinglog_count`` is COUNT(*) over the shelves, unweighted."""
    counts = dump.count_reading_log(fx.reading_log_lines(), min_count=1)

    # The fragment carries every shelving row of the boundary works, so these
    # counts are the real ones: 4 / 5 / 19 / 20 on the 2026-08-31 dump.
    assert counts["OL4619760W"] == 4
    assert counts["OL5920528W"] == 5
    assert counts["OL983047W"] == 19
    assert counts["OL27714493W"] == 20


def test_count_reading_log_prunes_below_the_whitelist_floor():
    """The floor is the lower of the two feature-73 thresholds, not a literal."""
    counts = dump.count_reading_log(fx.reading_log_lines())

    assert dump.whitelist_threshold() == settings.BOOKS_SEED_MIN_READINGLOG_ES == 5
    assert "OL4619760W" not in counts  # 4 shelvings: cannot qualify either stream
    assert counts["OL5920528W"] == 5  # exactly on the floor


def test_whitelist_threshold_follows_the_settings(monkeypatch):
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_READINGLOG", 7)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_READINGLOG_ES", 3)
    assert dump.whitelist_threshold() == 3


# ── Pass 2: aggregating editions ─────────────────────────────────────────────


def test_aggregate_editions_ignores_works_outside_the_whitelist():
    """An edition whose works[] points outside the whitelist is dropped.

    This is what bounds the memory of the 12,59 GB pass: the map only ever
    grows for the ~399 k shelved works, never for the ~39 M in the corpus.
    """
    lines = fx.edition_lines()
    outside = fx.line_with(lines, "OL14903289W")

    aggregates = dump.aggregate_editions(lines, {fx.WORK_PSICOLOGIA_OSCURA})

    assert set(aggregates) == {fx.WORK_PSICOLOGIA_OSCURA}
    # ...and the dropped line really is a well-formed edition of another work.
    parsed = dump.parse_dump_line(outside)
    assert parsed is not None and parsed[2]["works"][0]["key"] == "/works/OL14903289W"


def test_aggregate_editions_drops_the_works_of_a_shared_edition_that_are_not_wanted():
    """The inner guard: an edition can name several works, only some wanted.

    This one line is **synthetic**, and deliberately not in the recorded
    fragment: there is no edition with more than one entry in ``works[]`` in
    the 49 real editions of the fixture, nor in the first 6.430 lines of the
    editions dump sampled while building it. So the case cannot be *found*,
    only constructed — and it still has to be pinned, because this guard is what
    keeps the 12,59 GB pass from allocating an aggregate for a work nobody
    shelved. Without it the pre-filter (which matches the *line*, not each
    key) would let the unwanted sibling in.
    """
    line = "/type/edition\t/books/OL99999999M\t1\t2020-01-01T00:00:00\t" + json.dumps(
        {
            "key": "/books/OL99999999M",
            "title": "Two Works, One Edition",
            "number_of_pages": 300,
            "languages": [{"key": "/languages/eng"}],
            "publish_date": "2001",
            "works": [{"key": "/works/OL111111W"}, {"key": "/works/OL222222W"}],
        }
    )

    aggregates = dump.aggregate_editions([line], {"OL111111W"})

    assert set(aggregates) == {"OL111111W"}
    assert aggregates["OL111111W"].edition_count == 1
    # Both keys really are in the line: the drop is the guard's doing.
    assert "OL222222W" in line


def test_aggregate_editions_tolerates_an_edition_without_languages():
    """Editions with no ``languages`` still count, they just cast no language vote."""
    lines = fx.edition_lines()
    no_language = fx.line_with(lines, "OL10000798M")
    work_id = dump.parse_dump_line(no_language)[2]["works"][0]["key"].removeprefix("/works/")

    aggregates = dump.aggregate_editions([no_language], {work_id})

    aggregate = aggregates[work_id]
    assert aggregate.edition_count == 1
    assert aggregate.languages == set()
    assert aggregate.pages_median == 65


def test_merge_edition_aggregates_the_fields_solr_computes():
    aggregate = dump.EditionAggregate()
    dump.merge_edition(
        aggregate,
        {
            "languages": [{"key": "/languages/eng"}],
            "number_of_pages": 100,
            "publish_date": "December 31, 1990",
            "isbn_10": ["0000000001"],
            "dewey_decimal_class": ["813/.54"],
            "lc_classifications": ["PS3563.O8749"],
            "covers": [-1, 42],
        },
    )
    dump.merge_edition(
        aggregate,
        {
            "languages": [{"key": "/languages/spa"}],
            "number_of_pages": 300,
            "publish_date": "1975",
            "isbn_13": ["9780000000002"],
            "covers": [77],
        },
    )

    assert aggregate.edition_count == 2
    assert aggregate.languages == {"eng", "spa"}
    assert aggregate.pages_median == 200  # ceil(median([100, 300]))
    assert aggregate.first_publish_year == 1975  # min, like Solr's first_publish_year
    assert aggregate.isbn == "0000000001"  # first edition wins, deterministic
    assert aggregate.cover_id == 42  # -1 means "no cover" and is skipped
    assert aggregate.ddc == ["813/.54"]
    assert aggregate.lcc == ["PS3563.O8749"]


def test_merge_edition_prefers_isbn_13_within_an_edition():
    aggregate = dump.EditionAggregate()
    dump.merge_edition(aggregate, {"isbn_10": ["0000000001"], "isbn_13": ["9780000000002"]})
    assert aggregate.isbn == "9780000000002"


@pytest.mark.parametrize(
    ("publish_date", "expected"),
    [
        # Every form below except the last three is in the real corpus; the
        # first eight are in this fixture alone. ``publish_date`` is free text.
        ("1997", 1997),
        ("2005-03-17", 2005),
        ("December 31, 1990", 1990),
        ("Dec 04, 2018", 2018),
        ("nov 15 2018", 2018),
        ("4/12/2018", 2018),
        ("28 septembre 2023", 2023),
        ("Octubre 2021", 2021),
        ("c1985", 1985),  # circa: no word boundary before the digits
        ("[1985]", 1985),  # supplied by the cataloguer
        ("1985?", 1985),  # uncertain
        ("n.d.", None),
        ("9780132275880", None),  # a longer digit run is not a year
        (None, None),
        (1997, None),  # not a string: Open Library data is not schema-checked
    ],
)
def test_publish_year_extraction(publish_date, expected):
    aggregate = dump.EditionAggregate()
    dump.merge_edition(aggregate, {"publish_date": publish_date})
    assert aggregate.first_publish_year == expected


def test_pages_median_follows_open_librarys_own_rule():
    """Only a *missing* page count abstains, and the median is rounded up.

    Both halves are upstream's, not ours: ``number_of_pages_median`` in
    ``openlibrary/solr/updater/work.py`` is ``ceil(median(...))`` over the
    editions whose ``number_of_pages`` ``is not None`` — so an explicit ``0``
    votes, and a median landing on a half rounds up.
    """
    aggregate = dump.EditionAggregate()
    for pages in (None, 100, 0, 400, "many"):
        dump.merge_edition(aggregate, {"number_of_pages": pages})
    assert aggregate.edition_count == 5
    assert aggregate.pages_median == 100  # median of [100, 0, 400]

    rounded_up = dump.EditionAggregate()
    for pages in (100, 101):
        dump.merge_edition(rounded_up, {"number_of_pages": pages})
    assert rounded_up.pages_median == 101  # ceil(100.5), not int(100.5)


def test_pages_median_is_none_when_no_edition_declares_pages():
    aggregate = dump.EditionAggregate()
    dump.merge_edition(aggregate, {})
    assert aggregate.pages_median is None


# ── Selection: the feature-73 filter ─────────────────────────────────────────


def _aggregate(*, languages, editions, pages):
    return dump.EditionAggregate(
        edition_count=editions, languages=set(languages), pages=[pages] if pages else []
    )


def test_select_language_english_stream_thresholds():
    passing = _aggregate(languages=["eng"], editions=10, pages=100)
    assert dump.select_language(20, passing) == "eng"

    assert dump.select_language(19, passing) is None  # readinglog floor
    assert dump.select_language(20, _aggregate(languages=["eng"], editions=9, pages=100)) is None
    assert dump.select_language(20, _aggregate(languages=["eng"], editions=10, pages=99)) is None
    assert dump.select_language(20, _aggregate(languages=["eng"], editions=10, pages=0)) is None


def test_select_language_spanish_stream_uses_its_own_floors():
    spanish = _aggregate(languages=["spa"], editions=2, pages=100)
    assert dump.select_language(5, spanish) == "spa"
    assert dump.select_language(4, spanish) is None
    assert dump.select_language(5, _aggregate(languages=["spa"], editions=1, pages=100)) is None


def test_select_language_reproduces_not_language_eng():
    """A work with both languages belongs to the English stream only.

    The Solr query is ``language:spa AND NOT language:eng`` because
    ``language`` is multivalued at work level; without that half the Spanish
    stream would return the English list.
    """
    both = _aggregate(languages=["eng", "spa"], editions=2, pages=100)
    assert dump.select_language(5, both) is None  # Spanish floors do not apply
    assert dump.select_language(20, _aggregate(languages=["eng", "spa"], editions=10, pages=100))


def test_select_language_ignores_works_in_neither_language():
    assert dump.select_language(999, _aggregate(languages=["fre"], editions=99, pages=999)) is None


def test_select_language_reads_thresholds_at_call_time(monkeypatch):
    aggregate = _aggregate(languages=["eng"], editions=3, pages=120)
    assert dump.select_language(6, aggregate) is None
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_READINGLOG", 5)
    monkeypatch.setattr(settings, "BOOKS_SEED_MIN_EDITIONS", 3)
    assert dump.select_language(6, aggregate) == "eng"


def test_select_works_orders_and_filters():
    aggregates = {
        "OL2W": _aggregate(languages=["eng"], editions=10, pages=100),
        "OL1W": _aggregate(languages=["eng"], editions=10, pages=100),
        "OL3W": _aggregate(languages=["eng"], editions=1, pages=100),
    }
    counts = {"OL1W": 30, "OL2W": 30, "OL3W": 30}

    selected = dump.select_works(counts, aggregates)

    assert [work.work_id for work in selected] == ["OL1W", "OL2W"]
    assert selected[0].readinglog_count == 30
    assert selected[0].language == "eng"


def test_select_works_treats_an_unknown_work_as_zero_shelvings():
    aggregates = {"OL1W": _aggregate(languages=["eng"], editions=10, pages=100)}
    assert dump.select_works({}, aggregates) == []


# ── Pass 3 and 4: works and authors ──────────────────────────────────────────


def test_parse_work_record_reads_both_description_shapes():
    plain = dump.parse_work_record("OL1W", {"title": "T", "description": "plain"})
    typed = dump.parse_work_record(
        "OL1W", {"title": "T", "description": {"type": "/type/text", "value": "typed"}}
    )
    empty = dump.parse_work_record("OL1W", {"title": "T"})

    assert plain.description == "plain"
    assert typed.description == "typed"
    assert empty.description is None


def test_parse_work_record_reads_author_keys_once():
    record = {
        "title": "T",
        "authors": [
            {"author": {"key": "/authors/OL1A"}},
            {"author": {"key": "/authors/OL1A"}},
            {"author": {"key": "/authors/OL2A"}},
            {"junk": True},
        ],
    }
    assert dump.parse_work_record("OL1W", record).author_ids == ["OL1A", "OL2A"]


def test_collect_work_records_only_keeps_the_wanted_works():
    lines = fx.work_lines()
    records = dump.collect_work_records(lines, {fx.WORK_PSICOLOGIA_OSCURA})
    assert set(records) == {fx.WORK_PSICOLOGIA_OSCURA}
    assert records[fx.WORK_PSICOLOGIA_OSCURA].title


def test_collect_author_names_falls_back_to_personal_name():
    line = (
        "/type/author\t/authors/OL9999999A\t1\t2020-01-01\t" + '{"personal_name": "Only Personal"}'
    )
    assert dump.collect_author_names([line], {"OL9999999A"}) == {"OL9999999A": "Only Personal"}


def test_author_rows_skips_an_author_missing_from_the_dump():
    """A work still gets seeded with one credit fewer, never an empty-named row.

    Same graceful degradation ``collect_book_authors`` has for a failed
    ``/authors/{id}`` request — only here the cause is an author key the
    authors dump does not carry.
    """
    rows = dump.author_rows(["OL1A", "OL_MISSING_A"], {"OL1A": "Ada Lovelace"})

    assert [row.external_id for row in rows] == ["OL1A"]
    assert rows[0].role == "AUTHOR"
    assert rows[0].source == "OPEN_LIBRARY"
    assert rows[0].slug == "ada-lovelace"
    assert rows[0].profile_url is None


def test_author_rows_falls_back_to_the_olid_for_a_non_latin_name():
    """Issue #18: a name that folds to "" would collapse on uq_people_slug."""
    rows = dump.author_rows(["OL7000A"], {"OL7000A": "宮崎駿"})
    assert rows[0].slug == "open-library-ol7000a"


# ── The search-doc bridge ────────────────────────────────────────────────────


def test_build_search_doc_has_the_shape_book_to_dict_consumes():
    work = dump.WorkRecord(
        work_id="OL1W",
        title="A Title",
        subjects=["Fiction"],
        cover_id=None,
        description="desc",
        author_ids=["OL1A"],
    )
    aggregate = dump.EditionAggregate(
        edition_count=12,
        languages={"eng"},
        pages=[200],
        ddc=["813.6"],
        lcc=["PS3563.O8749"],
        isbn="9780000000002",
        first_publish_year=1999,
        cover_id=555,
    )
    doc = dump.build_search_doc(dump.SelectedWork("OL1W", "eng", 40, aggregate), work)

    assert doc == {
        "key": "/works/OL1W",
        "title": "A Title",
        "first_publish_year": 1999,
        "cover_i": 555,  # work has none: falls back to the first edition cover
        "isbn": ["9780000000002"],
        "ddc": ["813.6"],
        "lcc": ["PS3563.O8749"],
        "subject_facet": ["Fiction"],
    }


def test_build_search_doc_prefers_the_works_own_cover():
    work = dump.WorkRecord("OL1W", "T", [], 111, None, [])
    aggregate = dump.EditionAggregate(cover_id=222)
    doc = dump.build_search_doc(dump.SelectedWork("OL1W", "eng", 40, aggregate), work)
    assert doc["cover_i"] == 111


def test_build_work_detail_carries_only_the_description():
    """``first_publish_date`` is deliberately not passed to ``book_to_dict``.

    Solr ignores the work's own date and derives the year from the editions;
    reading it here would move the year — and with it the slug — away from the
    value already persisted for books seeded through ``search.json``.
    """
    with_description = dump.WorkRecord("OL1W", "T", [], None, "desc", [])
    without = dump.WorkRecord("OL1W", "T", [], None, None, [])

    assert dump.build_work_detail(with_description) == {"description": "desc"}
    assert dump.build_work_detail(without) is None


# ── Streaming ────────────────────────────────────────────────────────────────


def _patch_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Route the module's ``httpx.Client`` through a mock transport."""
    original_client = httpx.Client

    def patched_client(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr(dump.httpx, "Client", patched_client)


def test_stream_dump_lines_decompresses_the_response_on_the_fly(monkeypatch):
    """The gzip stream is decoded straight off the socket, never through disk."""
    payload = gzip.compress(b"first line\nsecond line\n")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=payload)

    _patch_client(monkeypatch, httpx.MockTransport(handler))

    assert list(dump.stream_dump_lines(dump.DUMP_WORKS)) == ["first line", "second line"]
    assert seen["url"] == dump.dump_url("works")


def test_stream_dump_lines_retries_a_connection_lost_before_any_data(monkeypatch):
    """A reset while opening the stream is free to redo — so it is redone.

    Measured on a real run: archive.org reset the works pass four seconds in,
    right after two hours of downloading editions. Retrying there costs
    nothing; the phase-level artifacts already protect everything before it.
    """
    payload = gzip.compress(b"only line\n")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("Connection reset by peer", request=request)
        return httpx.Response(200, content=payload)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setattr(dump, "_DUMP_RETRY_BACKOFF_S", 0)

    assert list(dump.stream_dump_lines(dump.DUMP_WORKS)) == ["only line"]
    assert calls["n"] == 2


class _CutOffStream(httpx.SyncByteStream):
    """A response body that hands out real bytes and then drops the connection.

    This is what archive.org does after half an hour, and it is the only way
    to exercise the *mid-stream* half of the retry rule: a truncated gzip body
    cannot do it, because it fails while decompressing rather than while
    reading, at a different layer and with a different exception.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __iter__(self):
        yield from self._chunks
        raise httpx.ReadError("connection lost mid-stream")


# ``gzip`` pulls ``READ_BUFFER_SIZE`` (128 KiB) of *compressed* bytes before it
# hands back a single decompressed byte, so a body cut earlier than that never
# produces a line and would make the mid-stream test vacuous. The fixture is
# sized around that, not around a guess.
_CUT_OFF_LINES = 300_000
_CUT_OFF_AT = 4 * gzip.READ_BUFFER_SIZE


def _cut_off_body(line_count: int, cut_at: int) -> tuple[list[bytes], list[str]]:
    """Gzip *line_count* unique lines and cut the body after *cut_at* bytes."""
    expected = [f"line {index}" for index in range(line_count)]
    body = gzip.compress(("\n".join(expected) + "\n").encode())
    assert len(body) > cut_at, "the body must be longer than the cut, or nothing is cut off"
    return [body[:cut_at]], expected


def test_stream_dump_lines_never_retries_after_handing_out_a_single_line(monkeypatch):
    """The half of the rule that protects the data, not the run.

    A retry here would re-open the dump and re-emit from the top, so the
    caller would count the same editions twice: ``edition_count`` inflated,
    ``readinglog_count`` inflated, works clearing the feature-73 filter that
    should not, and **no counter anywhere would move**. That is the shape of
    failure issue #22 exists to prevent, so the guard is pinned by its two
    observable consequences: exactly one open, and no repeated line.
    """
    chunks, _ = _cut_off_body(_CUT_OFF_LINES, _CUT_OFF_AT)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, stream=_CutOffStream(chunks))

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setattr(dump, "_DUMP_RETRY_BACKOFF_S", 0)
    # httpx buffers up to ``chunk_size`` before yielding anything, so the
    # production 1 MB chunk would swallow this fixture whole. Shrink the
    # transport chunk, not the rule under test.
    monkeypatch.setattr(dump, "_CHUNK_SIZE", 8192)

    received: list[str] = []
    with pytest.raises(httpx.ReadError):
        for line in dump.stream_dump_lines(dump.DUMP_WORKS):
            received.append(line)

    assert received, "the body must hand out lines before the cut, or this proves nothing"
    assert calls["n"] == 1, "the stream was re-opened after data had been handed out"
    assert len(received) == len(set(received)), "the caller was fed the same lines twice"


def test_stream_dump_lines_treats_a_truncated_body_the_same_way(monkeypatch):
    """A body that just *ends* is the same cut, seen one layer up.

    A truncated gzip raises ``EOFError`` while decompressing instead of
    ``ReadError`` while reading. Before feature 87's round 3 that difference
    meant it escaped the retry clause entirely — same situation, different
    behaviour, by accident. It is in ``_RETRYABLE_STREAM_ERRORS`` now, so the
    one rule that matters still applies: lines were handed out, so no retry.
    """
    payload = gzip.compress(b"first\nsecond\n")[:30]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=payload)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setattr(dump, "_DUMP_RETRY_BACKOFF_S", 0)

    received: list[str] = []
    with pytest.raises(EOFError):
        for line in dump.stream_dump_lines(dump.DUMP_WORKS):
            received.append(line)

    assert received == ["first", "second"]
    assert calls["n"] == 1


def test_stream_dump_lines_retries_a_body_that_dies_before_any_line(monkeypatch):
    """Symmetric check: with nothing handed out, the same failure IS retried.

    Without this the previous two tests would also pass on a
    ``stream_dump_lines`` that never retried at all.
    """
    good = gzip.compress(b"only line\n")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, stream=_CutOffStream([]))
        return httpx.Response(200, content=good)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setattr(dump, "_DUMP_RETRY_BACKOFF_S", 0)

    assert list(dump.stream_dump_lines(dump.DUMP_WORKS)) == ["only line"]
    assert calls["n"] == 2


def test_stream_dump_lines_gives_up_after_the_attempt_budget(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("down", request=request)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setattr(dump, "_DUMP_RETRY_BACKOFF_S", 0)

    with pytest.raises(httpx.ConnectError):
        list(dump.stream_dump_lines(dump.DUMP_WORKS))
    assert calls["n"] == dump._DUMP_CONNECT_ATTEMPTS


def test_dump_url_points_at_the_latest_monthly_dump():
    assert dump.dump_url(dump.DUMP_EDITIONS) == (
        "https://openlibrary.org/data/ol_dump_editions_latest.txt.gz"
    )
