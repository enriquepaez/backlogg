from datetime import UTC, datetime

from backlogg.movies.repository import get_movie_by_slug, upsert_movie


def _movie_data(slug: str, title: str = "Test Movie") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test movie overview.",
        "release_date": None,
        "runtime": 120,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Action", "slug": "action"}],
    }


async def test_upsert_movie(db):
    """Upsert a movie and verify fields and genres are persisted."""
    data = _movie_data("test-movie-2001")
    movie = await upsert_movie(db, data)

    assert movie.id is not None
    assert movie.title == "Test Movie"
    assert movie.slug == "test-movie-2001"
    assert movie.runtime == 120
    assert movie.status == "Released"
    assert len(movie.genres) == 1
    assert movie.genres[0].name == "Action"
    assert movie.genres[0].slug == "action"


async def test_upsert_movie_idempotent(db):
    """Upserting the same slug twice does not create a duplicate."""
    data1 = _movie_data("test-movie-2002", title="Original Title")
    movie1 = await upsert_movie(db, data1)

    data2 = _movie_data("test-movie-2002", title="Updated Title")
    movie2 = await upsert_movie(db, data2)

    assert movie1.id == movie2.id
    assert movie2.title == "Updated Title"


async def test_get_movie_by_slug_not_found(db):
    """Querying a non-existent slug returns None."""
    result = await get_movie_by_slug(db, "slug-that-does-not-exist-9999")
    assert result is None


async def test_upsert_movie_multiple_genres(db):
    """Upsert a movie with multiple genres."""
    from datetime import date

    data = {
        "title": "Multi Genre Movie",
        "original_title": "Multi Genre Movie",
        "slug": "multi-genre-movie-2003",
        "overview": None,
        "release_date": date(2003, 6, 15),
        "runtime": 90,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": 1000000,
        "revenue": 5000000,
        "status": "Released",
        "rating_external": 7.5,
        "rating_count_external": 1000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [
            {"name": "Drama", "slug": "drama"},
            {"name": "Comedy", "slug": "comedy"},
        ],
    }
    movie = await upsert_movie(db, data)

    assert movie.release_date is not None
    assert movie.budget == 1000000
    assert len(movie.genres) == 2
    genre_names = {g.name for g in movie.genres}
    assert genre_names == {"Drama", "Comedy"}
