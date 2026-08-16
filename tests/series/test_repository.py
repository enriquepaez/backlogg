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


# ── locked_fields (feature 49 — catalog_manual_edit) ─────────────────────────


async def test_upsert_series_skips_locked_scalar_field(db):
    """A column listed in locked_fields survives a sync upsert untouched."""
    data1 = _series_data("test-series-locked-title", title="Original Title")
    series1 = await upsert_series(db, data1)
    series1.locked_fields = ["title"]
    await db.flush()

    data2 = _series_data("test-series-locked-title", title="Synced Title")
    series2 = await upsert_series(db, data2)

    assert series2.id == series1.id
    assert series2.title == "Original Title"


async def test_upsert_series_updates_unlocked_field(db):
    """A column NOT in locked_fields still syncs normally, even if others are locked."""
    data1 = _series_data("test-series-unlocked-status", title="Original Title")
    series1 = await upsert_series(db, data1)
    series1.locked_fields = ["title"]
    await db.flush()

    data2 = dict(_series_data("test-series-unlocked-status", title="Synced Title"))
    data2["status"] = "Canceled"
    series2 = await upsert_series(db, data2)

    assert series2.title == "Original Title"
    assert series2.status == "Canceled"


async def test_upsert_series_skips_locked_genres(db):
    """genres in locked_fields skips the genre re-sync block entirely."""
    data1 = _series_data("test-series-locked-genres")
    series1 = await upsert_series(db, data1)
    assert {g.name for g in series1.genres} == {"Drama"}
    series1.locked_fields = ["genres"]
    await db.flush()

    data2 = _series_data("test-series-locked-genres")
    data2["genres"] = [{"name": "Comedy", "slug": "comedy"}]
    series2 = await upsert_series(db, data2)

    assert {g.name for g in series2.genres} == {"Drama"}
