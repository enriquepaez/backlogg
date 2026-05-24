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
