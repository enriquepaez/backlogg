from datetime import UTC, datetime

from backlogg.series.repository import get_series_by_slug, upsert_series


def _series_data(slug: str, title: str = "Test Series") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test series overview.",
        "first_air_date": None,
        "last_air_date": None,
        "number_of_seasons": 3,
        "number_of_episodes": 30,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Drama", "slug": "drama"}],
    }


async def test_upsert_series(db):
    """Upsert a series and verify fields and genres are persisted."""
    data = _series_data("test-series-2001")
    series = await upsert_series(db, data)

    assert series.id is not None
    assert series.title == "Test Series"
    assert series.slug == "test-series-2001"
    assert series.number_of_seasons == 3
    assert series.number_of_episodes == 30
    assert series.status == "Ended"
    assert len(series.genres) == 1
    assert series.genres[0].name == "Drama"
    assert series.genres[0].slug == "drama"


async def test_upsert_series_idempotent(db):
    """Upserting the same slug twice does not create a duplicate."""
    data1 = _series_data("test-series-2002", title="Original Title")
    series1 = await upsert_series(db, data1)

    data2 = _series_data("test-series-2002", title="Updated Title")
    series2 = await upsert_series(db, data2)

    assert series1.id == series2.id
    assert series2.title == "Updated Title"


async def test_get_series_by_slug_not_found(db):
    """Querying a non-existent slug returns None."""
    result = await get_series_by_slug(db, "slug-that-does-not-exist-9999")
    assert result is None
