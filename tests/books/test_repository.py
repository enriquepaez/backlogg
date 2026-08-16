from datetime import UTC, date, datetime

from backlogg.books.repository import get_book_by_slug, upsert_book


def _book_data(slug: str, title: str = "Test Book") -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "A test book overview.",
        "first_publish_date": None,
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Fiction", "slug": "fiction"}],
    }


async def test_upsert_book(db):
    """Upsert a book and verify fields and genres are persisted."""
    data = _book_data("test-book-2001")
    book = await upsert_book(db, data)

    assert book.id is not None
    assert book.title == "Test Book"
    assert book.slug == "test-book-2001"
    assert len(book.genres) == 1
    assert book.genres[0].name == "Fiction"
    assert book.genres[0].slug == "fiction"


async def test_upsert_book_idempotent(db):
    """Upserting the same slug twice does not create a duplicate."""
    data1 = _book_data("test-book-2002", title="Original Title")
    book1 = await upsert_book(db, data1)

    data2 = _book_data("test-book-2002", title="Updated Title")
    book2 = await upsert_book(db, data2)

    assert book1.id == book2.id
    assert book2.title == "Updated Title"


async def test_get_book_by_slug_not_found(db):
    """Querying a non-existent slug returns None."""
    result = await get_book_by_slug(db, "slug-that-does-not-exist-9999")
    assert result is None


async def test_upsert_book_with_publish_date(db):
    """Upsert a book with a first_publish_date."""
    data = {
        "title": "Classic Novel",
        "original_title": None,
        "slug": "classic-novel-1925",
        "overview": "A classic.",
        "first_publish_date": date(1925, 4, 10),
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [
            {"name": "Literary Fiction", "slug": "literary-fiction"},
            {"name": "Modernism", "slug": "modernism"},
        ],
    }
    book = await upsert_book(db, data)

    assert book.first_publish_date == date(1925, 4, 10)
    assert len(book.genres) == 2
    genre_names = {g.name for g in book.genres}
    assert genre_names == {"Literary Fiction", "Modernism"}


# ── locked_fields (feature 49 — catalog_manual_edit) ─────────────────────────


async def test_upsert_book_skips_locked_scalar_field(db):
    """A column listed in locked_fields survives a sync upsert untouched."""
    data1 = _book_data("test-book-locked-title", title="Original Title")
    book1 = await upsert_book(db, data1)
    book1.locked_fields = ["title"]
    await db.flush()

    data2 = _book_data("test-book-locked-title", title="Synced Title")
    book2 = await upsert_book(db, data2)

    assert book2.id == book1.id
    assert book2.title == "Original Title"


async def test_upsert_book_updates_unlocked_field(db):
    """A column NOT in locked_fields still syncs normally, even if others are locked."""
    data1 = _book_data("test-book-unlocked-language", title="Original Title")
    book1 = await upsert_book(db, data1)
    book1.locked_fields = ["title"]
    await db.flush()

    data2 = dict(_book_data("test-book-unlocked-language", title="Synced Title"))
    data2["original_language"] = "fr"
    book2 = await upsert_book(db, data2)

    assert book2.title == "Original Title"
    assert book2.original_language == "fr"


async def test_upsert_book_skips_locked_genres(db):
    """genres in locked_fields skips the genre re-sync block entirely."""
    data1 = _book_data("test-book-locked-genres")
    book1 = await upsert_book(db, data1)
    assert {g.name for g in book1.genres} == {"Fiction"}
    book1.locked_fields = ["genres"]
    await db.flush()

    data2 = _book_data("test-book-locked-genres")
    data2["genres"] = [{"name": "Poetry", "slug": "poetry"}]
    book2 = await upsert_book(db, data2)

    assert {g.name for g in book2.genres} == {"Fiction"}
