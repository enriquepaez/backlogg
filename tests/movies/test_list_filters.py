"""Repository tests for catalog search filters on movies (feature 50).

Covers each new ``list_movies`` filter individually (``search``, ``date_from``/
``date_to``, ``rating_internal_min``/``max``, ``rating_external_min``/``max``)
plus combinations with each other and with the existing ``genre`` filter.
"""

from datetime import UTC, date, datetime

from backlogg.movies.repository import list_movies, upsert_movie
from backlogg.movies.schemas import MovieSortEnum
from backlogg.shared.catalog_filters import CatalogSearchFilters


def _movie_data(
    slug: str,
    title: str,
    release_date: date | None,
    rating_external: float | None,
    rating_internal: float | None,
    genres: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test movie overview.",
        "release_date": release_date,
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": rating_external,
        "rating_count_external": 100,
        "rating_internal": rating_internal,
        "rating_count_internal": 5,
        "last_synced_at": datetime.now(UTC),
        "genres": genres or [],
    }


async def _seed(db):
    await upsert_movie(
        db,
        _movie_data(
            "filters-dune-2021",
            "Dune",
            date(2021, 10, 22),
            7.8,
            4.2,
            genres=[{"name": "mv-filters-scifi", "slug": "mv-filters-scifi"}],
        ),
    )
    await upsert_movie(
        db,
        _movie_data(
            "filters-dune-part-two-2024",
            "Dune Part Two",
            date(2024, 3, 1),
            8.5,
            4.7,
            genres=[{"name": "mv-filters-scifi", "slug": "mv-filters-scifi"}],
        ),
    )
    await upsert_movie(
        db,
        _movie_data(
            "filters-other-movie-2010",
            "Some Other Movie",
            date(2010, 5, 1),
            5.0,
            2.0,
            genres=[{"name": "mv-filters-drama", "slug": "mv-filters-drama"}],
        ),
    )


async def _slugs(db, filters: CatalogSearchFilters, genre: str | None = None) -> set[str]:
    items, _ = await list_movies(
        db, genre=genre, sort=MovieSortEnum.title_asc, page=1, limit=50, filters=filters
    )
    return {m.slug for m in items}


async def test_list_movies_no_filters_returns_all(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters())
    assert {"filters-dune-2021", "filters-dune-part-two-2024", "filters-other-movie-2010"} <= slugs


async def test_list_movies_search_is_case_insensitive_substring(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(search="dUnE"))
    assert slugs == {"filters-dune-2021", "filters-dune-part-two-2024"}


async def test_list_movies_date_from_only(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(date_from=date(2021, 1, 1)))
    assert slugs == {"filters-dune-2021", "filters-dune-part-two-2024"}


async def test_list_movies_date_to_only(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(date_to=date(2021, 12, 31)))
    assert slugs == {"filters-dune-2021", "filters-other-movie-2010"}


async def test_list_movies_date_range_inclusive_both_bounds(db):
    await _seed(db)
    slugs = await _slugs(
        db, CatalogSearchFilters(date_from=date(2021, 10, 22), date_to=date(2021, 10, 22))
    )
    assert slugs == {"filters-dune-2021"}


async def test_list_movies_rating_internal_range(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(rating_internal_min=4.0, rating_internal_max=5.0))
    assert slugs == {"filters-dune-2021", "filters-dune-part-two-2024"}


async def test_list_movies_rating_external_range(db):
    await _seed(db)
    slugs = await _slugs(
        db, CatalogSearchFilters(rating_external_min=8.0, rating_external_max=10.0)
    )
    assert slugs == {"filters-dune-part-two-2024"}


async def test_list_movies_filters_combine_with_genre_and_each_other(db):
    await _seed(db)
    slugs = await _slugs(
        db,
        CatalogSearchFilters(
            search="dune",
            date_from=date(2022, 1, 1),
            rating_internal_min=4.5,
            rating_external_min=8.0,
        ),
        genre="mv-filters-scifi",
    )
    assert slugs == {"filters-dune-part-two-2024"}


async def test_list_movies_filters_narrow_to_empty_result(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(search="dune", rating_internal_max=1.0))
    assert slugs == set()
