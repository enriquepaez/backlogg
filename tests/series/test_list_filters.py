"""Repository tests for catalog search filters on series (feature 50).

Covers each new ``list_series`` filter individually (``search``, ``date_from``/
``date_to`` over ``first_air_date``, ``rating_internal_min``/``max``,
``rating_external_min``/``max``) plus combinations with each other and with
the existing ``genre`` filter.
"""

from datetime import UTC, date, datetime

from backlogg.series.repository import list_series, upsert_series
from backlogg.series.schemas import SeriesSortEnum
from backlogg.shared.catalog_filters import CatalogSearchFilters


def _series_data(
    slug: str,
    title: str,
    first_air_date: date | None,
    rating_external: float | None,
    rating_internal: float | None,
    genres: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test series overview.",
        "first_air_date": first_air_date,
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 8,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": rating_external,
        "rating_count_external": 100,
        "rating_internal": rating_internal,
        "rating_count_internal": 5,
        "last_synced_at": datetime.now(UTC),
        "genres": genres or [],
    }


async def _seed(db):
    await upsert_series(
        db,
        _series_data(
            "filters-succession-2018",
            "Succession",
            date(2018, 6, 3),
            8.8,
            4.6,
            genres=[{"name": "sr-filters-drama", "slug": "sr-filters-drama"}],
        ),
    )
    await upsert_series(
        db,
        _series_data(
            "filters-succession-side-2022",
            "Succession Side Story",
            date(2022, 1, 1),
            7.0,
            3.5,
            genres=[{"name": "sr-filters-drama", "slug": "sr-filters-drama"}],
        ),
    )
    await upsert_series(
        db,
        _series_data(
            "filters-other-series-2005",
            "Some Other Series",
            date(2005, 1, 1),
            5.0,
            2.0,
            genres=[{"name": "sr-filters-comedy", "slug": "sr-filters-comedy"}],
        ),
    )


async def _slugs(db, filters: CatalogSearchFilters, genre: str | None = None) -> set[str]:
    items, _ = await list_series(
        db, genre=genre, sort=SeriesSortEnum.title_asc, page=1, limit=50, filters=filters
    )
    return {s.slug for s in items}


async def test_list_series_search_is_case_insensitive_substring(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(search="SUCCEssion"))
    assert slugs == {"filters-succession-2018", "filters-succession-side-2022"}


async def test_list_series_date_range_on_first_air_date(db):
    await _seed(db)
    slugs = await _slugs(
        db, CatalogSearchFilters(date_from=date(2010, 1, 1), date_to=date(2020, 1, 1))
    )
    assert slugs == {"filters-succession-2018"}


async def test_list_series_rating_internal_range(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(rating_internal_min=4.0, rating_internal_max=5.0))
    assert slugs == {"filters-succession-2018"}


async def test_list_series_rating_external_range(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(rating_external_min=7.0, rating_external_max=9.0))
    assert slugs == {"filters-succession-2018", "filters-succession-side-2022"}


async def test_list_series_filters_combine_with_genre_and_each_other(db):
    await _seed(db)
    slugs = await _slugs(
        db,
        CatalogSearchFilters(search="succession", rating_internal_min=4.0),
        genre="sr-filters-drama",
    )
    assert slugs == {"filters-succession-2018"}
