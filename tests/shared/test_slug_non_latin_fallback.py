"""Issue #18 — names and titles in non-Latin scripts must not slugify to "".

``_slugify`` folded to ASCII and nothing else, so anything written entirely in
CJK, Cyrillic, Arabic, Greek… came back empty:

* people upsert on ``uq_people_slug``, so every non-Latin person collapsed into
  a single ``slug = ''`` row (and, since feature 84, had their credit dropped
  and counted in ``people_errors`` instead);
* items build ``f"{slug_base}-{year}"``, so ``''`` produced ``-2025`` and every
  non-Latin title of that year collapsed onto one slug.

The fix derives the slug from the external id when the fold comes back empty.
The rows below are the real ones measured on the dev database:

    movies id=137  '仙逆剧场版 弑仙之战'      -> slug ''
    series id=459  '初次尝鲜'                 -> slug '-2025'
    books  id=404  '人間失格'                 -> slug '-1948'
    books  id=435  'Преступление и наказание' -> slug '-1866'
    people id=1148 'Фёдор Достоевский'        -> slug ''

Two properties are load-bearing and are asserted explicitly:

1. **No regression on the already-seeded catalog** — a Latin title or name must
   produce byte-for-byte the slug it produced before this change.
2. **No new collisions** — two different non-Latin titles of the same year, and
   two different non-Latin people, must end up with different slugs.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from backlogg.books.adapters.open_library import OpenLibraryClient
from backlogg.books.service import collect_book_authors
from backlogg.games.adapters.igdb import IGDBClient
from backlogg.movies.adapters.tmdb import TMDBClient
from backlogg.movies.service import map_movie_credits
from backlogg.people import repository as people_repo
from backlogg.series.adapters.tmdb import TMDBSeriesClient
from backlogg.series.service import collect_series_creators, map_series_credits
from backlogg.shared.bulk_load import BulkPerson, bulk_load_credits
from backlogg.shared.models import Credit, Person
from backlogg.shared.slugs import (
    external_id_slug,
    slug_with_external_fallback,
    slugify,
    titled_slug,
)

# Titles/names of the already-seeded catalog and the slug they produce today.
# If any of these changes, the fix broke every URL already published.
_LATIN_REGRESSION_CASES = [
    ("The Matrix", "the-matrix"),
    ("Amélie", "amelie"),
    ("WALL·E", "walle"),
    ("Spider-Man: No Way Home", "spider-man-no-way-home"),
    ("Fyodor Dostoevsky", "fyodor-dostoevsky"),
    ("Hayao Miyazaki", "hayao-miyazaki"),
    ("Æon Flux", "on-flux"),
    ("¿Qué he hecho yo para merecer esto?", "que-he-hecho-yo-para-merecer-esto"),
    ("  leading and trailing  ", "leading-and-trailing"),
    ("Crime & Punishment", "crime-punishment"),
]

_NON_LATIN_NAMES = [
    "仙逆剧场版 弑仙之战",  # Chinese
    "初次尝鲜",  # Chinese
    "人間失格",  # Japanese
    "Преступление и наказание",  # Cyrillic
    "Фёдор Достоевский",  # Cyrillic
    "한영롱",  # Korean
    "نجيب محفوظ",  # Arabic
    "Νίκος Καζαντζάκης",  # Greek
    "עמוס עוז",  # Hebrew
]


# ── The helper itself ────────────────────────────────────────────────────────


@pytest.mark.parametrize(("text", "expected"), _LATIN_REGRESSION_CASES)
def test_slugify_is_unchanged_for_latin_text(text, expected):
    """The shared helper folds exactly like the five ``_slugify`` copies did."""
    assert slugify(text) == expected


@pytest.mark.parametrize("text", _NON_LATIN_NAMES)
def test_slugify_still_folds_non_latin_text_to_empty(text):
    """The fold itself is unchanged — the fallback lives one layer above."""
    assert slugify(text) == ""


@pytest.mark.parametrize(
    ("source", "external_id", "expected"),
    [
        ("TMDB", 1234567, "tmdb-1234567"),
        ("TMDB", "287", "tmdb-287"),
        ("OPEN_LIBRARY", "OL123W", "open-library-ol123w"),
        ("IGDB", 4567, "igdb-4567"),
    ],
)
def test_external_id_slug_format(source, external_id, expected):
    assert external_id_slug(source, external_id) == expected


@pytest.mark.parametrize("external_id", [None, ""])
def test_external_id_slug_is_empty_without_an_id(external_id):
    """No external identity, no fallback — the caller's validation must still fire."""
    assert external_id_slug("TMDB", external_id) == ""


def test_external_id_slug_is_empty_without_a_source():
    assert external_id_slug("", "1234567") == ""


@pytest.mark.parametrize(("text", "expected"), _LATIN_REGRESSION_CASES)
def test_slug_with_external_fallback_leaves_latin_text_alone(text, expected):
    assert slug_with_external_fallback(text, "TMDB", 999) == expected


@pytest.mark.parametrize(
    ("text", "source", "external_id", "expected"),
    [
        ("仙逆剧场版 弑仙之战", "TMDB", 1599191, "tmdb-1599191"),
        ("初次尝鲜", "TMDB", "305977", "tmdb-305977"),
        ("人間失格", "OPEN_LIBRARY", "OL3923952W", "open-library-ol3923952w"),
        ("Преступление и наказание", "OPEN_LIBRARY", "OL166894W", "open-library-ol166894w"),
        ("Фёдор Достоевский", "OPEN_LIBRARY", "OL22242A", "open-library-ol22242a"),
        ("한영롱", "TMDB", 3311, "tmdb-3311"),
        ("نجيب محفوظ", "OPEN_LIBRARY", "OL118077A", "open-library-ol118077a"),
        ("Νίκος Καζαντζάκης", "OPEN_LIBRARY", "OL27362A", "open-library-ol27362a"),
        ("ドラゴンクエスト", "IGDB", 4567, "igdb-4567"),
        ("עמוס עוז", "OPEN_LIBRARY", "OL39304A", "open-library-ol39304a"),
    ],
)
def test_slug_with_external_fallback_uses_the_external_id(text, source, external_id, expected):
    """Each script against the source it really comes from, not one literal."""
    assert slug_with_external_fallback(text, source, external_id) == expected


def test_slug_with_external_fallback_keeps_a_mixed_script_title():
    """A title with *some* Latin content still slugifies from the title."""
    assert slug_with_external_fallback("初次尝鲜 Season 2", "TMDB", 305977) == "season-2"


def test_titled_slug_appends_the_year_for_latin_titles():
    assert titled_slug("The Matrix", "1999", "TMDB", 603) == "the-matrix-1999"


def test_titled_slug_without_a_year_is_just_the_fold():
    assert titled_slug("The Matrix", "", "TMDB", 603) == "the-matrix"


def test_titled_slug_drops_the_year_suffix_on_the_fallback():
    """The external id is already unique; the year would only make it longer."""
    assert titled_slug("初次尝鲜", "2025", "TMDB", 305977) == "tmdb-305977"
    assert (
        titled_slug("人間失格", "1948", "OPEN_LIBRARY", "OL3923952W") == "open-library-ol3923952w"
    )


# ── Items: the four adapters ─────────────────────────────────────────────────


def _movie_raw(tmdb_id: int, title: str, release_date: str | None) -> dict:
    return {"id": tmdb_id, "title": title, "release_date": release_date or "", "genres": []}


def _series_raw(tmdb_id: int, name: str, first_air_date: str | None) -> dict:
    return {"id": tmdb_id, "name": name, "first_air_date": first_air_date or "", "genres": []}


def _book_doc(work_id: str, title: str, year: int | None) -> dict:
    return {"key": f"/works/{work_id}", "title": title, "first_publish_year": year}


def test_movie_to_dict_keeps_the_slug_of_the_seeded_catalog():
    """Regression guard: a Latin title still produces exactly today's slug."""
    result = TMDBClient().movie_to_dict(_movie_raw(603, "The Matrix", "1999-03-30"))
    assert result["slug"] == "the-matrix-1999"


def test_movie_to_dict_falls_back_to_the_tmdb_id():
    """The real dev-DB row: movies id=137 used to land with slug ''."""
    result = TMDBClient().movie_to_dict(_movie_raw(1599191, "仙逆剧场版 弑仙之战", None))
    assert result["slug"] == "tmdb-1599191"


def test_series_to_dict_falls_back_to_the_tmdb_id():
    """The real dev-DB row: series id=459 used to land with slug '-2025'."""
    result = TMDBSeriesClient().series_to_dict(_series_raw(305977, "初次尝鲜", "2025-01-10"))
    assert result["slug"] == "tmdb-305977"


def test_series_to_dict_keeps_the_slug_of_the_seeded_catalog():
    result = TMDBSeriesClient().series_to_dict(_series_raw(1396, "Breaking Bad", "2008-01-20"))
    assert result["slug"] == "breaking-bad-2008"


def test_book_to_dict_falls_back_to_the_open_library_id():
    """The real dev-DB rows: books id=404 ('-1948') and id=435 ('-1866')."""
    ol = OpenLibraryClient()
    assert (
        ol.book_to_dict(_book_doc("OL3923952W", "人間失格", 1948))["slug"]
        == "open-library-ol3923952w"
    )
    assert (
        ol.book_to_dict(_book_doc("OL166894W", "Преступление и наказание", 1866))["slug"]
        == "open-library-ol166894w"
    )


def test_book_to_dict_keeps_the_slug_of_the_seeded_catalog():
    result = OpenLibraryClient().book_to_dict(_book_doc("OL82563W", "Harry Potter", 1997))
    assert result["slug"] == "harry-potter-1997"


def test_game_to_dict_falls_back_to_the_igdb_id():
    """IGDB usually ships its own slug; when it does not, the name must not fold to ''."""
    result = IGDBClient().game_to_dict({"id": 4567, "name": "ドラゴンクエスト"})
    assert result["slug"] == "igdb-4567"


def test_game_to_dict_prefers_the_igdb_slug():
    result = IGDBClient().game_to_dict(
        {"id": 4567, "name": "The Witcher 3", "slug": "the-witcher-3"}
    )
    assert result["slug"] == "the-witcher-3"


# ── No new collisions ────────────────────────────────────────────────────────


def test_two_non_latin_movies_of_the_same_year_get_different_slugs():
    """Before the fix both landed on '-2025' and upsert_movie merged them."""
    client = TMDBClient()
    first = client.movie_to_dict(_movie_raw(111, "仙逆剧场版 弑仙之战", "2025-04-01"))
    second = client.movie_to_dict(_movie_raw(222, "初次尝鲜", "2025-08-15"))
    assert first["slug"] != second["slug"]
    assert "" not in (first["slug"], second["slug"])


def test_two_non_latin_series_of_the_same_year_get_different_slugs():
    client = TMDBSeriesClient()
    first = client.series_to_dict(_series_raw(111, "初次尝鲜", "2025-01-10"))
    second = client.series_to_dict(_series_raw(222, "한영롱", "2025-06-01"))
    assert first["slug"] != second["slug"]


def test_two_non_latin_books_of_the_same_year_get_different_slugs():
    ol = OpenLibraryClient()
    first = ol.book_to_dict(_book_doc("OL1W", "人間失格", 1948))
    second = ol.book_to_dict(_book_doc("OL2W", "斜陽", 1948))
    assert first["slug"] != second["slug"]


def test_two_non_latin_people_get_different_slugs():
    """The core of issue #18: distinct people must never share a slug."""
    rows = map_movie_credits(
        {
            "cast": [
                {"id": 1148, "name": "Фёдор Достоевский"},
                {"id": 2296, "name": "韩晓晖"},
                {"id": 3311, "name": "한영롱"},
            ],
            "crew": [],
        }
    )
    slugs = [row.slug for row in rows]
    assert slugs == ["tmdb-1148", "tmdb-2296", "tmdb-3311"]
    assert len(set(slugs)) == 3


# ── People: every mapper that builds a BulkPerson ────────────────────────────


def test_map_movie_credits_keeps_latin_names_unchanged():
    rows = map_movie_credits(
        {
            "cast": [{"id": 6384, "name": "Keanu Reeves", "character": "Neo", "order": 0}],
            "crew": [{"id": 9339, "name": "Lana Wachowski", "job": "Director"}],
        }
    )
    assert [row.slug for row in rows] == ["keanu-reeves", "lana-wachowski"]


def test_map_movie_credits_falls_back_for_a_non_latin_director():
    rows = map_movie_credits(
        {"cast": [], "crew": [{"id": 608, "name": "宮崎駿", "job": "Director"}]}
    )
    assert [row.slug for row in rows] == ["tmdb-608"]


def test_map_series_credits_falls_back_for_a_non_latin_actor():
    """The exact payload of the issue: series 305977, actor '韩晓晖'."""
    rows = map_series_credits({"cast": [{"id": 2296, "name": "韩晓晖", "order": 0}]})
    assert [row.slug for row in rows] == ["tmdb-2296"]


def test_collect_series_creators_falls_back_for_a_non_latin_creator():
    """The other half of the issue: series 65270, creator '한영롱'."""
    rows = collect_series_creators([{"id": 3311, "name": "한영롱"}])
    assert [(row.name, row.slug, row.role) for row in rows] == [("한영롱", "tmdb-3311", "CREATOR")]


@pytest.mark.asyncio
async def test_collect_book_authors_falls_back_for_a_non_latin_author():
    """books id=435 'Преступление и наказание' — its author folded to '' too."""
    work_detail = {"authors": [{"author": {"key": "/authors/OL22242A"}}]}
    with patch(
        "backlogg.books.service._ol_client.get_author",
        new=AsyncMock(return_value={"name": "Фёдор Достоевский"}),
    ):
        rows = await collect_book_authors(work_detail)
    assert [(row.name, row.slug) for row in rows] == [
        ("Фёдор Достоевский", "open-library-ol22242a")
    ]


@pytest.mark.asyncio
async def test_collect_book_authors_keeps_latin_names_unchanged():
    work_detail = {"authors": [{"author": {"key": "/authors/OL23919A"}}]}
    with patch(
        "backlogg.books.service._ol_client.get_author",
        new=AsyncMock(return_value={"name": "J. K. Rowling"}),
    ):
        rows = await collect_book_authors(work_detail)
    assert [row.slug for row in rows] == ["j-k-rowling"]


# ── The batch route stops dropping these credits ─────────────────────────────


@pytest.mark.asyncio
async def test_bulk_load_credits_no_longer_rejects_non_latin_people(db):
    """The validation that counts ``people_errors`` stays — it just stops firing.

    Reproduces the symptom reported in the issue (``people_errors=2`` on
    ``POST /admin/sync/series``) with the very same names, and asserts both
    people land as distinct rows with their credits attached.
    """
    people = map_series_credits({"cast": [{"id": 92296, "name": "韩晓晖", "order": 0}]})
    people += collect_series_creators([{"id": 93311, "name": "한영롱"}])
    assert len(people) == 2

    outcome = await bulk_load_credits(db, "SERIES", [(4590, people)])

    assert outcome.people_rejected == 0

    slugs = ["tmdb-92296", "tmdb-93311"]
    rows = (await db.execute(select(Person).where(Person.slug.in_(slugs)))).scalars().all()
    assert sorted(p.slug for p in rows) == slugs
    assert {p.name for p in rows} == {"韩晓晖", "한영롱"}

    credits = (
        (
            await db.execute(
                select(Credit).where(Credit.item_type == "SERIES", Credit.item_id == 4590)
            )
        )
        .scalars()
        .all()
    )
    assert len(credits) == 2
    assert {c.person_id for c in credits} == {p.id for p in rows}


@pytest.mark.asyncio
async def test_bulk_load_credits_still_rejects_a_genuinely_incomplete_payload(db):
    """The guard must keep protecting against payloads with no identity at all."""
    outcome = await bulk_load_credits(
        db,
        "SERIES",
        [
            (
                4591,
                [
                    BulkPerson(
                        source="TMDB",
                        external_id="",
                        name="韩晓晖",
                        slug="",
                        profile_url=None,
                        role="ACTOR",
                    )
                ],
            )
        ],
    )
    assert outcome.people_rejected == 1


# ── The per-item route ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_non_latin_people_do_not_collapse_in_the_per_item_route(db):
    """``upsert_person`` merges on ``uq_people_slug`` — an empty slug ate them all."""
    now = datetime.now(UTC)
    first = await people_repo.get_or_create_person_by_external(
        db,
        "TMDB",
        "91148",
        "Фёдор Достоевский",
        slug_fallback("Фёдор Достоевский", "91148"),
        None,
        now,
    )
    second = await people_repo.get_or_create_person_by_external(
        db, "TMDB", "92296", "韩晓晖", slug_fallback("韩晓晖", "92296"), None, now
    )
    assert first.id != second.id
    assert first.slug == "tmdb-91148"
    assert second.slug == "tmdb-92296"


@pytest.mark.asyncio
async def test_get_or_create_person_by_external_derives_a_missing_slug(db):
    """Last line of defence for a caller that forgot to apply the fallback."""
    person = await people_repo.get_or_create_person_by_external(
        db, "OPEN_LIBRARY", "OL22242A", "Фёдор Достоевский", "", None, datetime.now(UTC)
    )
    assert person.slug == "open-library-ol22242a"


def slug_fallback(name: str, external_id: str) -> str:
    """The slug the credit mappers build for a TMDB person."""
    return slug_with_external_fallback(name, "TMDB", external_id)


# ── The dates the adapters parse are unaffected by the slug change ───────────


def test_fallback_slug_does_not_disturb_the_rest_of_the_payload():
    result = TMDBClient().movie_to_dict(_movie_raw(1599191, "仙逆剧场版 弑仙之战", "2025-04-01"))
    assert result["title"] == "仙逆剧场版 弑仙之战"
    assert result["release_date"] == date(2025, 4, 1)
    assert result["slug"] == "tmdb-1599191"


# ── The four slug *prediction* sites ─────────────────────────────────────────
#
# Four call sites do not build a slug to persist it: they build the slug they
# expect the adapter to produce, so they can look the item up locally and skip
# a network round trip (``trending/service.py`` x2, the similar/recommended
# paths of ``movies`` and ``series``).  Prediction and generation are two
# separate expressions over two separate inputs (the *list*-format payload vs.
# the *detail* payload), and nothing in the type system ties them together —
# that divergence is the mechanism that produced this issue in the first place.
#
# So these tests never compare against a literal.  They run the real function,
# capture the slug it hands to the local lookup, and compare it against what
# the adapter really returns for the same item.  Reverting any of the four to
# the pre-fix ``f"{slugify(title)}-{year}"`` must fail here.

_CJK_MOVIE_ID = 771001
_CJK_SERIES_ID = 771002
_CJK_REC_MOVIE_ID = 771003
_CJK_REC_SERIES_ID = 771004
_SOURCE_MOVIE_ID = 771005
_SOURCE_SERIES_ID = 771006


def _cjk_movie_detail(tmdb_id: int, title: str = "仙逆剧场版 弑仙之战") -> dict:
    """A TMDB *detail* payload — the shape ``movie_to_dict`` consumes."""
    return {
        "id": tmdb_id,
        "title": title,
        "original_title": title,
        "overview": "",
        "release_date": "2025-04-01",
        "runtime": 100,
        "original_language": "zh",
        "poster_path": None,
        "backdrop_path": None,
        "budget": 0,
        "revenue": 0,
        "status": "Released",
        "vote_average": 7.0,
        "vote_count": 120,
        "genres": [],
    }


def _cjk_movie_list_item(tmdb_id: int, title: str = "仙逆剧场版 弑仙之战") -> dict:
    """The *list* payload of the same movie — what the prediction sites get."""
    return {
        "id": tmdb_id,
        "title": title,
        "release_date": "2025-04-01",
        "poster_path": None,
        "vote_average": 7.0,
        "vote_count": 120,
    }


def _cjk_series_detail(tmdb_id: int, name: str = "初次尝鲜") -> dict:
    return {
        "id": tmdb_id,
        "name": name,
        "original_name": name,
        "overview": "",
        "first_air_date": "2025-01-10",
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 8,
        "status": "Ended",
        "original_language": "zh",
        "poster_path": None,
        "backdrop_path": None,
        "vote_average": 7.5,
        "vote_count": 90,
        "genres": [],
        "created_by": [],
    }


def _cjk_series_list_item(tmdb_id: int, name: str = "初次尝鲜") -> dict:
    return {
        "id": tmdb_id,
        "name": name,
        "first_air_date": "2025-01-10",
        "poster_path": None,
        "vote_average": 7.5,
        "vote_count": 90,
    }


def _latin_movie_detail(tmdb_id: int, title: str) -> dict:
    detail = _cjk_movie_detail(tmdb_id, title)
    detail["release_date"] = "1999-03-30"
    return detail


def _latin_series_detail(tmdb_id: int, name: str) -> dict:
    detail = _cjk_series_detail(tmdb_id, name)
    detail["first_air_date"] = "2008-01-20"
    return detail


def _slug_spy(module, attr: str):
    """Patch a ``get_*_by_slug`` lookup so every slug it is asked for is kept."""
    real = getattr(module, attr)
    seen: list[str] = []

    async def spy(db, slug):
        seen.append(slug)
        return await real(db, slug)

    return patch.object(module, attr, new=spy), seen


@pytest.mark.asyncio
async def test_trending_movie_predicts_the_slug_the_adapter_generates(db):
    """``trending/service.py`` — prediction must match ``movie_to_dict``."""
    from backlogg.movies import repository as movies_repo
    from backlogg.trending.service import _ingest_trending_movie

    detail = _cjk_movie_detail(_CJK_MOVIE_ID)
    expected = TMDBClient().movie_to_dict(dict(detail))["slug"]
    detail_mock = AsyncMock(return_value=detail)
    spy, seen = _slug_spy(movies_repo, "get_movie_by_slug")

    with (
        spy,
        patch("backlogg.trending.service._movies_tmdb.get_movie_detail", new=detail_mock),
        patch("backlogg.movies.service._tmdb.get_movie_credits", new=AsyncMock(return_value=None)),
    ):
        first = await _ingest_trending_movie(db, _cjk_movie_list_item(_CJK_MOVIE_ID))
        # Second pass: the prediction must now hit the row the first pass wrote.
        second = await _ingest_trending_movie(db, _cjk_movie_list_item(_CJK_MOVIE_ID))

    assert seen == [expected, expected]
    assert first is not None and first.slug == expected
    assert second is not None and second.slug == expected
    detail_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_trending_series_predicts_the_slug_the_adapter_generates(db):
    """``trending/service.py`` — prediction must match ``series_to_dict``."""
    from backlogg.series import repository as series_repo
    from backlogg.trending.service import _ingest_trending_series

    detail = _cjk_series_detail(_CJK_SERIES_ID)
    expected = TMDBSeriesClient().series_to_dict(dict(detail))["slug"]
    detail_mock = AsyncMock(return_value=detail)
    spy, seen = _slug_spy(series_repo, "get_series_by_slug")

    with (
        spy,
        patch("backlogg.trending.service._series_tmdb.get_series_detail", new=detail_mock),
        patch("backlogg.series.service._tmdb.get_series_credits", new=AsyncMock(return_value=None)),
    ):
        first = await _ingest_trending_series(db, _cjk_series_list_item(_CJK_SERIES_ID))
        second = await _ingest_trending_series(db, _cjk_series_list_item(_CJK_SERIES_ID))

    assert seen == [expected, expected]
    assert first is not None and first.slug == expected
    assert second is not None and second.slug == expected
    detail_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_similar_movies_predicts_the_slug_the_adapter_generates(db):
    """``movies/service.py`` — the recommendation prediction must match the adapter."""
    from backlogg.movies import repository as movies_repo
    from backlogg.movies.service import get_similar_movies
    from backlogg.shared.external_ids import upsert_external_id

    client = TMDBClient()
    source = await movies_repo.upsert_movie(
        db, client.movie_to_dict(_latin_movie_detail(_SOURCE_MOVIE_ID, "Slug Prediction Source"))
    )
    await upsert_external_id(db, "MOVIE", source.id, "TMDB", str(_SOURCE_MOVIE_ID))
    await db.commit()

    rec_detail = _cjk_movie_detail(_CJK_REC_MOVIE_ID)
    expected = client.movie_to_dict(dict(rec_detail))["slug"]
    detail_mock = AsyncMock(return_value=rec_detail)
    spy, seen = _slug_spy(movies_repo, "get_movie_by_slug")

    with (
        spy,
        patch(
            "backlogg.movies.service._tmdb.get_movie_recommendations",
            new=AsyncMock(return_value=[_cjk_movie_list_item(_CJK_REC_MOVIE_ID)]),
        ),
        patch("backlogg.movies.service._tmdb.get_movie_detail", new=detail_mock),
        patch("backlogg.movies.service._tmdb.get_movie_credits", new=AsyncMock(return_value=None)),
    ):
        first = await get_similar_movies(db, source.slug)
        second = await get_similar_movies(db, source.slug)

    # The source lookup happens first on each pass; the prediction is the second.
    assert seen == [source.slug, expected, source.slug, expected]
    assert [r.slug for r in first.results] == [expected]
    assert [r.slug for r in second.results] == [expected]
    detail_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_similar_series_predicts_the_slug_the_adapter_generates(db):
    """``series/service.py`` — the recommendation prediction must match the adapter."""
    from backlogg.series import repository as series_repo
    from backlogg.series.service import get_similar_series
    from backlogg.shared.external_ids import upsert_external_id

    client = TMDBSeriesClient()
    source = await series_repo.upsert_series(
        db, client.series_to_dict(_latin_series_detail(_SOURCE_SERIES_ID, "Slug Prediction Show"))
    )
    await upsert_external_id(db, "SERIES", source.id, "TMDB", str(_SOURCE_SERIES_ID))
    await db.commit()

    rec_detail = _cjk_series_detail(_CJK_REC_SERIES_ID)
    expected = client.series_to_dict(dict(rec_detail))["slug"]
    detail_mock = AsyncMock(return_value=rec_detail)
    spy, seen = _slug_spy(series_repo, "get_series_by_slug")

    with (
        spy,
        patch(
            "backlogg.series.service._tmdb.get_series_recommendations",
            new=AsyncMock(return_value=[_cjk_series_list_item(_CJK_REC_SERIES_ID)]),
        ),
        patch("backlogg.series.service._tmdb.get_series_detail", new=detail_mock),
        patch("backlogg.series.service._tmdb.get_series_credits", new=AsyncMock(return_value=None)),
    ):
        first = await get_similar_series(db, source.slug)
        second = await get_similar_series(db, source.slug)

    assert seen == [source.slug, expected, source.slug, expected]
    assert [r.slug for r in first.results] == [expected]
    assert [r.slug for r in second.results] == [expected]
    detail_mock.assert_awaited_once()


# ── The one hole the fallback cannot fill, and who catches it ────────────────
#
# ``titled_slug`` returns "" when the title folds to nothing **and** there is
# no external id to fall back to.  It does not raise: an on-demand path is
# entered *by* an external id and cannot reach the case, and turning that into
# a 500 would be worse than the bug.  The invariant is enforced at the two item
# write frontiers instead — the item is dropped and counted, never persisted
# with the "" slug that would make the next such item upsert onto its row.
#
# The reachable route is the hand-built ``search_doc`` in
# ``scheduler/jobs.py::sync_books``, which copies ``"key"`` by hand (the same
# shape of mistake that was issue #17 with ``isbn``).


def test_book_to_dict_yields_an_empty_slug_without_a_work_key():
    """The precondition of the guards below — documented, not desired."""
    doc = {"key": "", "title": "人間失格", "first_publish_year": 1948}
    assert OpenLibraryClient().book_to_dict(doc)["slug"] == ""


@pytest.mark.asyncio
async def test_bulk_load_items_rejects_an_item_with_no_slug(db):
    """Batch frontier: dropped and counted in ``rejected``, never written."""
    from backlogg.books import repository as books_repo
    from backlogg.books.models import Book
    from backlogg.shared.bulk_load import BulkItem, bulk_load_items

    payload = OpenLibraryClient().book_to_dict(
        {"key": "", "title": "人間失格", "first_publish_year": 1948}
    )
    assert payload["slug"] == ""

    outcome = await bulk_load_items(db, books_repo.BOOK_BULK_SPEC, [BulkItem(data=payload)])

    assert (outcome.written, outcome.rejected) == (0, 1)
    assert (await db.execute(select(Book).where(Book.slug == ""))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_write_items_individually_rejects_an_item_with_no_slug(db):
    """Per-item frontier: same invariant, counted in ``errors``."""
    from backlogg.books import repository as books_repo
    from backlogg.books.models import Book
    from backlogg.scheduler.jobs import _write_items_individually
    from backlogg.shared.bulk_load import BulkItem

    payload = OpenLibraryClient().book_to_dict(
        {"key": "", "title": "Преступление и наказание", "first_publish_year": 1866}
    )
    assert payload["slug"] == ""

    synced, errors, people_errors = await _write_items_individually(
        db, books_repo.BOOK_BULK_SPEC, [BulkItem(data=payload)], "test_issue_18"
    )

    assert (synced, errors, people_errors) == (0, 1, 0)
    assert (await db.execute(select(Book).where(Book.slug == ""))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_a_normal_book_still_goes_through_both_frontiers(db):
    """The guards must not cost a legitimate non-Latin book its row."""
    from backlogg.books import repository as books_repo
    from backlogg.books.models import Book
    from backlogg.shared.bulk_load import BulkItem, bulk_load_items

    payload = OpenLibraryClient().book_to_dict(
        {"key": "/works/OL771111W", "title": "人間失格", "first_publish_year": 1948}
    )
    assert payload["slug"] == "open-library-ol771111w"

    outcome = await bulk_load_items(
        db, books_repo.BOOK_BULK_SPEC, [BulkItem(data=dict(payload), external_id="OL771111W")]
    )
    assert (outcome.written, outcome.rejected) == (1, 0)
    row = (
        await db.execute(select(Book).where(Book.slug == "open-library-ol771111w"))
    ).scalar_one_or_none()
    assert row is not None and row.title == "人間失格"
