"""The dump path must agree with ``search.json``, proved on real data (feature 87).

This is the test the acceptance criteria of feature 87 ask for: the criteria of
feature 72 (genres from ``ddc``/``lcc``) and feature 73 (notoriety from
``readinglog_count``/``edition_count``) have to survive the move from
``search.json`` to the monthly dumps.  So nothing here is asserted against
hand-written literals: every expectation is **what the ``search.json`` path
produces for the same works**, recorded alongside the dump fragment.

The fixture is real: verbatim lines of the 2026-08-31 dump plus the live
``search.json`` docs of the same five works — see
``tests/books/fixtures/openlibrary_dump/README.md``.  The interesting part is
that the two sides do *not* carry the same input: Open Library normalises
``ddc``/``lcc`` for Solr (``"PZ-0007.00000000.R79835"``) and leaves them raw in
the editions (``"PZ7 .R79835"``, ``"303.48/33"``).  Agreement therefore proves
the existing parsers cope with the raw notation, which until now was only ever
argued from reading the code.
"""

import pytest

from backlogg.books.adapters import openlibrary_dump as dump
from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.books.constants import BOOK_LANGUAGE_EN, BOOK_LANGUAGE_ES
from backlogg.core.config import settings
from tests.books import dump_fixtures as fx

_client = OpenLibraryClient()


@pytest.fixture(scope="module")
def pipeline():
    """Run the four dump passes over the fixture, exactly as the script does."""
    counts = dump.count_reading_log(fx.reading_log_lines())
    aggregates = dump.aggregate_editions(fx.edition_lines(), counts)
    selected = {work.work_id: work for work in dump.select_works(counts, aggregates)}
    records = dump.collect_work_records(fx.work_lines(), selected)
    wanted = {author for record in records.values() for author in record.author_ids}
    names = dump.collect_author_names(fx.author_lines(), wanted)
    return {
        "counts": counts,
        "aggregates": aggregates,
        "selected": selected,
        "records": records,
        "names": names,
    }


def _solr_verdict(doc: dict) -> str | None:
    """The feature-73 filter expressed over a ``search.json`` doc.

    Literally ``build_seed_query`` read as a predicate: the same thresholds,
    the same ``NOT language:eng`` on the Spanish stream.  Used as the oracle
    the dump-side selection is compared against.
    """
    languages = doc.get("language") or []
    pages = doc.get("number_of_pages_median")
    editions = doc.get("edition_count") or 0
    shelvings = doc.get("readinglog_count") or 0
    if pages is None or pages < settings.BOOKS_SEED_MIN_PAGES:
        return None
    if BOOK_LANGUAGE_EN in languages:
        if (
            shelvings >= settings.BOOKS_SEED_MIN_READINGLOG
            and editions >= settings.BOOKS_SEED_MIN_EDITIONS
        ):
            return BOOK_LANGUAGE_EN
        return None
    if BOOK_LANGUAGE_ES in languages:
        if (
            shelvings >= settings.BOOKS_SEED_MIN_READINGLOG_ES
            and editions >= settings.BOOKS_SEED_MIN_EDITIONS_ES
        ):
            return BOOK_LANGUAGE_ES
        return None
    return None


# ── Feature 73: notoriety ────────────────────────────────────────────────────


def test_aggregates_reproduce_the_fields_solr_computes(pipeline):
    """``edition_count``, languages, pages median and year, dump vs Solr.

    These four are the whole of the feature-73 filter's input, and Open
    Library computes them from the editions.  Recomputing them from the dump
    has to land on the same numbers or the catalog would not be the same one.
    """
    docs = fx.search_docs()

    for work_id, aggregate in pipeline["aggregates"].items():
        doc = docs[work_id]
        assert aggregate.edition_count == doc["edition_count"], work_id
        assert aggregate.pages_median == doc["number_of_pages_median"], work_id
        assert aggregate.languages == set(doc["language"]), work_id
        assert aggregate.first_publish_year == doc["first_publish_year"], work_id


def test_selection_verdict_matches_the_search_json_path(pipeline):
    """Same works in, same yes/no out — for every work in the fragment."""
    docs = fx.search_docs()

    for work_id, aggregate in pipeline["aggregates"].items():
        shelvings = pipeline["counts"][work_id]
        assert dump.select_language(shelvings, aggregate) == _solr_verdict(docs[work_id]), work_id


def test_the_work_under_the_english_floor_is_rejected_by_both_paths(pipeline):
    """Ultramarathon Man: 19 shelvings against a floor of 20, on both sides.

    The one work in the fragment whose verdict is decided by the shelving
    count alone (11 editions, 295 pages, English), and the reason the fragment
    carries *all* 19 of its real reading-log rows: the count is the real one,
    not a sample, so the boundary is tested where it actually is.
    """
    assert pipeline["counts"][fx.WORK_ULTRAMARATHON] == 19
    assert fx.WORK_ULTRAMARATHON in pipeline["aggregates"]
    assert fx.WORK_ULTRAMARATHON not in pipeline["selected"]
    assert _solr_verdict(fx.search_docs()[fx.WORK_ULTRAMARATHON]) is None


def test_the_spanish_stream_selects_its_work(pipeline):
    """Two editions and 205 pages clear the Spanish floors and only those."""
    selected = pipeline["selected"][fx.WORK_PSICOLOGIA_OSCURA]
    assert selected.language == BOOK_LANGUAGE_ES
    assert selected.aggregate.edition_count < settings.BOOKS_SEED_MIN_EDITIONS


# ── Feature 72: classification ───────────────────────────────────────────────


def test_the_dump_carries_raw_ddc_and_lcc_notation(pipeline):
    """The premise of the next test: the two sides are *not* fed the same text.

    Solr normalises the call numbers into a sortable form; the editions carry
    what the cataloguer typed.  If this ever stopped being true the agreement
    below would prove nothing.
    """
    docs = fx.search_docs()
    normalized = [value for doc in docs.values() for value in (doc.get("lcc") or [])]
    raw = [
        value for work_id, aggregate in pipeline["aggregates"].items() for value in aggregate.lcc
    ]

    assert normalized, "the search docs must carry lcc for this test to mean anything"
    assert raw, "the dump fragment must carry lcc for this test to mean anything"
    assert all("-" in value and "." in value for value in normalized)
    assert not any(value.startswith(("PS-", "GV-", "V--")) for value in raw)


def test_genres_derived_from_the_dump_match_the_search_json_path(pipeline):
    """Feature 72 preserved: same genres, from raw notation instead of normalized."""
    docs = fx.search_docs()

    for work_id, work in pipeline["selected"].items():
        record = pipeline["records"][work_id]
        from_dump = _client.book_to_dict(dump.build_search_doc(work, record))
        from_search = _client.book_to_dict(docs[work_id])

        assert from_dump["genres"] == from_search["genres"], work_id


def test_every_selected_work_gets_at_least_the_same_core_fields(pipeline):
    """Title, slug and publication date must not drift between the two paths.

    The slug is the load-bearing one: books already seeded through
    ``search.json`` are upserted on it, so a dump run that computed it
    differently would duplicate the catalog instead of refreshing it.
    """
    docs = fx.search_docs()

    for work_id, work in pipeline["selected"].items():
        record = pipeline["records"][work_id]
        from_dump = _client.book_to_dict(dump.build_search_doc(work, record))
        from_search = _client.book_to_dict(docs[work_id])

        assert from_dump["title"] == from_search["title"], work_id
        assert from_dump["slug"] == from_search["slug"], work_id
        assert from_dump["first_publish_date"] == from_search["first_publish_date"], work_id
        assert from_dump["poster_url"] == from_search["poster_url"], work_id


def test_the_work_without_ddc_or_lcc_still_classifies_through_subjects(pipeline):
    """The third source: ``subject_facet`` — which is the work's own ``subjects``.

    Measured on the fixture: for all five works ``search.json``'s
    ``subject_facet`` is *exactly* the work record's ``subjects`` list, so the
    dump path can feed it straight through and reach the same genres.
    """
    work = pipeline["selected"][fx.WORK_SUMMER_TRILOGY]
    record = pipeline["records"][fx.WORK_SUMMER_TRILOGY]
    doc = fx.search_docs()[fx.WORK_SUMMER_TRILOGY]

    assert not work.aggregate.ddc and not work.aggregate.lcc
    assert sorted(record.subjects) == sorted(doc["subject_facet"])
    assert _client.book_to_dict(dump.build_search_doc(work, record))["genres"]


def test_a_work_with_no_classification_at_all_gets_no_genres(pipeline):
    """No ddc, no lcc, no subjects: better no genre than folksonomy noise."""
    work = pipeline["selected"][fx.WORK_PSICOLOGIA_OSCURA]
    record = pipeline["records"][fx.WORK_PSICOLOGIA_OSCURA]

    assert not work.aggregate.ddc and not work.aggregate.lcc and not record.subjects
    assert _client.book_to_dict(dump.build_search_doc(work, record))["genres"] == []


# ── Authorship ───────────────────────────────────────────────────────────────


def test_authorship_comes_from_the_authors_dump(pipeline):
    """Role AUTHOR rows built with zero ``/authors/{id}`` requests."""
    record = pipeline["records"][fx.WORK_LOVE_HYPOTHESIS]
    rows = dump.author_rows(record.author_ids, pipeline["names"])

    assert record.author_ids
    assert [row.role for row in rows] == ["AUTHOR"] * len(rows)
    assert all(row.source == "OPEN_LIBRARY" for row in rows)
    assert all(row.external_id.startswith("OL") for row in rows)
    assert all(row.slug and row.profile_url is None for row in rows)


def test_a_work_whose_author_is_missing_from_the_dump_still_seeds(pipeline):
    """The fragment deliberately omits one author line — see the README.

    Losing a credit must never lose the book: same graceful degradation the
    ``search.json`` path has when ``/authors/{id}`` fails.
    """
    missing = [
        (work_id, author_id)
        for work_id, record in pipeline["records"].items()
        for author_id in record.author_ids
        if author_id not in pipeline["names"]
    ]
    assert missing, "the fixture must keep one author out of authors.tsv"

    work_id, _ = missing[0]
    record = pipeline["records"][work_id]
    rows = dump.author_rows(record.author_ids, pipeline["names"])

    assert len(rows) == len(record.author_ids) - 1
    work = pipeline["selected"][work_id]
    assert _client.book_to_dict(dump.build_search_doc(work, record))["title"]


# ── Where the two paths deliberately differ ──────────────────────────────────


def test_the_two_deliberate_divergences_from_the_search_json_path(pipeline):
    """Two fields do *not* match, on purpose. Pinned so they stay deliberate.

    1. **``isbn``**. A work has one row and many editions, so "the" ISBN is a
       pick either way: ``search.json`` hands back its own edition ordering and
       the dump path takes the first edition it meets, preferring ISBN-13 over
       ISBN-10 inside that edition. Both are "an ISBN of this work"; the dump's
       pick is at least deterministic (edition-key order in the dump) and
       consistently ISBN-13 where one exists, which ``search.json`` is not.
    2. **``overview``**. The dump path fills it from the work's own
       ``description``, which the nightly ``search.json`` path *never* has —
       it calls ``book_to_dict`` with ``work_detail=None`` to avoid one more
       HTTP request per book. In the dumps the description costs nothing, so
       seeded books get the synopsis the on-demand path also gives them.
    """
    docs = fx.search_docs()
    isbn_differs = 0
    overview_gained = 0

    for work_id, work in pipeline["selected"].items():
        record = pipeline["records"][work_id]
        from_dump = _client.book_to_dict(
            dump.build_search_doc(work, record), dump.build_work_detail(record)
        )
        from_search = _client.book_to_dict(docs[work_id])

        if from_dump["isbn"] != from_search["isbn"]:
            isbn_differs += 1
        if from_dump["overview"] and not from_search["overview"]:
            overview_gained += 1
        # Whatever it picks, it is a real ISBN of one of the work's editions.
        if from_dump["isbn"]:
            assert any(from_dump["isbn"] in line for line in fx.edition_lines())

    assert isbn_differs, "if the ISBN pick ever converges, this note is stale"
    assert overview_gained, "the dump path must keep filling the synopsis"
