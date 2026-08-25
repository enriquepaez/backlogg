"""Repository tests for the rating_desc/rating_asc sort (feature 66).

sort=rating_desc/rating_asc must order by rating_internal (the community's
own rating) first — rating_external only breaks ties among items whose
rating_internal is NULL or equal, and never overrides a present
rating_internal value, no matter how much higher rating_external is.
"""

from datetime import UTC, date, datetime

from backlogg.movies.repository import list_movies, upsert_movie
from backlogg.movies.schemas import MovieSortEnum


def _movie_data(
    slug: str,
    title: str,
    rating_external: float | None,
    rating_internal: float | None,
) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test movie overview.",
        "release_date": date(2020, 1, 1),
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
        "genres": [{"name": "mv-rating-sort", "slug": "mv-rating-sort"}],
    }


async def _seed(db):
    # High rating_external but no rating_internal yet.
    await upsert_movie(db, _movie_data("rs-high-external-2020", "High External", 9.0, None))
    # Low rating_external but a solid rating_internal — must still outrank
    # the item above, since rating_internal is the primary criterion now.
    await upsert_movie(
        db, _movie_data("rs-low-external-high-internal-2020", "Low Ext High Int", 1.0, 3.0)
    )
    # Highest rating_internal of the three.
    await upsert_movie(db, _movie_data("rs-highest-internal-2020", "Highest Internal", 2.0, 4.5))


async def test_sort_rating_desc_prioritizes_internal_over_external(db):
    await _seed(db)
    items, _ = await list_movies(
        db, genre="mv-rating-sort", sort=MovieSortEnum.rating_desc, page=1, limit=50
    )
    slugs = [m.slug for m in items]
    assert slugs == [
        "rs-highest-internal-2020",
        "rs-low-external-high-internal-2020",
        "rs-high-external-2020",
    ]


async def test_sort_rating_asc_prioritizes_internal_over_external(db):
    """rating_internal ASC NULLS LAST: NULLs still sort last, not first —
    ascending only reorders the non-NULL values among themselves."""
    await _seed(db)
    items, _ = await list_movies(
        db, genre="mv-rating-sort", sort=MovieSortEnum.rating_asc, page=1, limit=50
    )
    slugs = [m.slug for m in items]
    assert slugs == [
        "rs-low-external-high-internal-2020",
        "rs-highest-internal-2020",
        "rs-high-external-2020",
    ]


async def test_sort_rating_desc_ties_break_on_external_desc(db):
    """When rating_internal is NULL for every candidate, rating_external decides."""
    await upsert_movie(db, _movie_data("rs-tie-low-ext-2021", "Tie Low Ext", 3.0, None))
    await upsert_movie(db, _movie_data("rs-tie-high-ext-2021", "Tie High Ext", 8.0, None))

    items, _ = await list_movies(
        db,
        genre=None,
        sort=MovieSortEnum.rating_desc,
        page=1,
        limit=200,
    )
    slugs = [m.slug for m in items]
    high_idx = slugs.index("rs-tie-high-ext-2021")
    low_idx = slugs.index("rs-tie-low-ext-2021")
    assert high_idx < low_idx
