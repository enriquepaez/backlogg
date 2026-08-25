"""Tests for get_similar_books (feature 46 — local-only, no external API)."""

from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException

from backlogg.books import repository as books_repo
from backlogg.books import service
from backlogg.people import repository as people_repo


def _book_data(
    slug: str,
    title: str = "Test Book",
    rating: float | None = None,
    genres: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "A test book.",
        "first_publish_date": None,
        "original_language": "en",
        "poster_url": None,
        "rating_external": rating,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": genres or [],
    }


async def _make_author(db, slug: str, name: str):
    return await people_repo.upsert_person(
        db,
        {
            "name": name,
            "slug": slug,
            "profile_url": None,
            "last_synced_at": datetime.now(UTC),
        },
    )


async def _credit_author(db, book_id: int, person_id: int) -> None:
    await people_repo.upsert_credit(
        db,
        {
            "item_type": "BOOK",
            "item_id": book_id,
            "person_id": person_id,
            "role": "AUTHOR",
            "character_name": None,
            "billing_order": None,
        },
    )


async def test_get_similar_books_404_for_unknown_slug(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.get_similar_books(db, "f46-slug-that-does-not-exist")
    assert exc_info.value.status_code == 404


async def test_get_similar_books_empty_when_no_genre_or_author(db):
    """A book with no genres and no author credits returns empty results, not an error."""
    await books_repo.upsert_book(db, _book_data("f46-lonely-book-2001"))

    result = await service.get_similar_books(db, "f46-lonely-book-2001")

    assert result.results == []


async def test_get_similar_books_excludes_source_book(db):
    """The source book never appears in its own results, even sharing its own genre."""
    genres = [{"name": "F46 Solo Genre", "slug": "f46-solo-genre"}]
    await books_repo.upsert_book(db, _book_data("f46-solo-book-2001", genres=genres))

    result = await service.get_similar_books(db, "f46-solo-book-2001")

    slugs = [r.slug for r in result.results]
    assert "f46-solo-book-2001" not in slugs
    assert result.results == []


async def test_get_similar_books_prioritizes_same_author_over_genre(db):
    """Author-shared books rank above genre-only matches."""
    genres = [{"name": "F46 Priority Genre", "slug": "f46-priority-genre"}]

    source = await books_repo.upsert_book(
        db, _book_data("f46-source-book-2001", rating=5.0, genres=genres)
    )
    author = await _make_author(db, "f46-priority-author", "F46 Priority Author")
    await _credit_author(db, source.id, author.id)

    # Same author, no shared genre, LOWER rating than the genre-only match.
    same_author_book = await books_repo.upsert_book(
        db, _book_data("f46-same-author-book-2002", rating=6.0)
    )
    await _credit_author(db, same_author_book.id, author.id)

    # Same genre, no shared author, HIGHER rating than the author match.
    await books_repo.upsert_book(
        db, _book_data("f46-same-genre-book-2003", rating=9.0, genres=genres)
    )

    result = await service.get_similar_books(db, "f46-source-book-2001")

    slugs = [r.slug for r in result.results]
    assert slugs == ["f46-same-author-book-2002", "f46-same-genre-book-2003"]


async def test_get_similar_books_falls_back_to_genre_when_no_author_match(db):
    """When the source book has no author credit, genre overlap is used instead."""
    genres = [{"name": "F46 Fallback Genre", "slug": "f46-fallback-genre"}]
    await books_repo.upsert_book(db, _book_data("f46-fallback-source-2001", genres=genres))
    genre_match = await books_repo.upsert_book(
        db, _book_data("f46-fallback-match-2002", rating=7.0, genres=genres)
    )

    result = await service.get_similar_books(db, "f46-fallback-source-2001")

    assert len(result.results) == 1
    assert result.results[0].slug == genre_match.slug


async def test_get_similar_books_tiebreaks_by_rating_desc(db):
    """Within the same priority tier, higher rating_external comes first."""
    genres = [{"name": "F46 Tiebreak Genre", "slug": "f46-tiebreak-genre"}]
    await books_repo.upsert_book(db, _book_data("f46-tiebreak-source-2001", genres=genres))
    low = await books_repo.upsert_book(
        db, _book_data("f46-tiebreak-low-2002", rating=3.0, genres=genres)
    )
    high = await books_repo.upsert_book(
        db, _book_data("f46-tiebreak-high-2003", rating=8.5, genres=genres)
    )

    result = await service.get_similar_books(db, "f46-tiebreak-source-2001")

    assert [r.slug for r in result.results] == [high.slug, low.slug]


async def test_get_similar_books_limits_to_10(db):
    """Only up to 10 results are returned even if more genre matches exist."""
    genres = [{"name": "F46 Limit Genre", "slug": "f46-limit-genre"}]
    await books_repo.upsert_book(db, _book_data("f46-limit-source-2001", genres=genres))
    for i in range(15):
        await books_repo.upsert_book(
            db, _book_data(f"f46-limit-match-{i}-2002", rating=float(i), genres=genres)
        )

    result = await service.get_similar_books(db, "f46-limit-source-2001")

    assert len(result.results) == 10


async def test_get_similar_books_response_shape(db):
    """Each result carries the shared similar-items contract fields."""
    genres = [{"name": "F46 Shape Genre", "slug": "f46-shape-genre"}]
    await books_repo.upsert_book(
        db, _book_data("f46-shape-source-2001", genres=genres, rating=None)
    )
    match_data = _book_data("f46-shape-match-2002", rating=6.7, genres=genres)
    match_data["first_publish_date"] = date(1999, 3, 1)
    match_data["poster_url"] = "https://covers.openlibrary.org/b/id/12345-L.jpg"
    match = await books_repo.upsert_book(db, match_data)

    result = await service.get_similar_books(db, "f46-shape-source-2001")

    assert len(result.results) == 1
    item = result.results[0]
    assert item.title == match.title
    assert item.slug == match.slug
    assert item.poster_url == "https://covers.openlibrary.org/b/id/12345-L.jpg"
    assert item.release_date == date(1999, 3, 1)
    assert item.rating_external == 6.7
    # Feature 69: rating_internal travels too, null when the book has none.
    assert item.rating_internal is None


async def test_get_similar_books_includes_rating_internal_value(db):
    """Feature 69: a candidate's non-null rating_internal travels in the response."""
    genres = [{"name": "F69 Internal Genre", "slug": "f69-internal-genre"}]
    await books_repo.upsert_book(
        db, _book_data("f69-internal-source-2001", genres=genres, rating=None)
    )
    match_data = _book_data("f69-internal-match-2002", rating=6.0, genres=genres)
    match_data["rating_internal"] = 4.35
    await books_repo.upsert_book(db, match_data)

    result = await service.get_similar_books(db, "f69-internal-source-2001")

    assert len(result.results) == 1
    assert result.results[0].rating_internal == 4.35
