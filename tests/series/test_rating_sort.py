"""Repository tests for the rating_desc/rating_asc sort (feature 66).

sort=rating_desc/rating_asc must order by rating_internal (the community's
own rating) first — rating_external only breaks ties among items whose
rating_internal is NULL or equal, and never overrides a present
rating_internal value, no matter how much higher rating_external is.
"""

from datetime import UTC, date, datetime

from backlogg.series.repository import list_series, upsert_series
from backlogg.series.schemas import SeriesSortEnum


def _series_data(
    slug: str,
    title: str,
    rating_external: float | None,
    rating_internal: float | None,
) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test series overview.",
        "first_air_date": date(2020, 1, 1),
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
        "genres": [{"name": "sr-rating-sort", "slug": "sr-rating-sort"}],
    }


async def _seed(db):
    await upsert_series(db, _series_data("rs-high-external-2020", "High External", 9.0, None))
    await upsert_series(
        db, _series_data("rs-low-external-high-internal-2020", "Low Ext High Int", 1.0, 3.0)
    )
    await upsert_series(db, _series_data("rs-highest-internal-2020", "Highest Internal", 2.0, 4.5))


async def test_sort_rating_desc_prioritizes_internal_over_external(db):
    await _seed(db)
    items, _ = await list_series(
        db, genre="sr-rating-sort", sort=SeriesSortEnum.rating_desc, page=1, limit=50
    )
    slugs = [s.slug for s in items]
    assert slugs == [
        "rs-highest-internal-2020",
        "rs-low-external-high-internal-2020",
        "rs-high-external-2020",
    ]


async def test_sort_rating_asc_prioritizes_internal_over_external(db):
    """rating_internal ASC NULLS LAST: NULLs still sort last, not first —
    ascending only reorders the non-NULL values among themselves."""
    await _seed(db)
    items, _ = await list_series(
        db, genre="sr-rating-sort", sort=SeriesSortEnum.rating_asc, page=1, limit=50
    )
    slugs = [s.slug for s in items]
    assert slugs == [
        "rs-low-external-high-internal-2020",
        "rs-highest-internal-2020",
        "rs-high-external-2020",
    ]


async def test_sort_rating_desc_ties_break_on_external_desc(db):
    """When rating_internal is NULL for every candidate, rating_external decides."""
    await upsert_series(db, _series_data("rs-tie-low-ext-2021", "Tie Low Ext", 3.0, None))
    await upsert_series(db, _series_data("rs-tie-high-ext-2021", "Tie High Ext", 8.0, None))

    items, _ = await list_series(db, genre=None, sort=SeriesSortEnum.rating_desc, page=1, limit=200)
    slugs = [s.slug for s in items]
    high_idx = slugs.index("rs-tie-high-ext-2021")
    low_idx = slugs.index("rs-tie-low-ext-2021")
    assert high_idx < low_idx
