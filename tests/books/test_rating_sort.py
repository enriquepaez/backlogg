"""Repository tests for the rating_desc/rating_asc sort (feature 66).

Covers both the main list sort (``list_books``) and the "similar books"
ranking (``get_books_by_same_authors`` / ``get_books_by_genre_overlap``),
which must order by rating_internal (the community's own rating) first —
rating_external only breaks ties among items whose rating_internal is NULL
or equal, and never overrides a present rating_internal value.
"""

from datetime import UTC, date, datetime

from backlogg.books.repository import (
    get_author_person_ids,
    get_books_by_genre_overlap,
    get_books_by_same_authors,
    list_books,
    upsert_book,
)
from backlogg.books.schemas import BookSortEnum
from backlogg.people.repository import upsert_credit, upsert_person


def _book_data(
    slug: str,
    title: str,
    rating_external: float | None,
    rating_internal: float | None,
    genres: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "A test book overview.",
        "first_publish_date": date(2020, 1, 1),
        "original_language": "en",
        "poster_url": None,
        "rating_external": rating_external,
        "rating_count_external": 100,
        "rating_internal": rating_internal,
        "rating_count_internal": 5,
        "last_synced_at": datetime.now(UTC),
        "genres": genres or [],
    }


async def _seed_list(db):
    await upsert_book(db, _book_data("bk-rs-high-external-2020", "High External", 9.0, None))
    await upsert_book(
        db, _book_data("bk-rs-low-external-high-internal-2020", "Low Ext High Int", 1.0, 3.0)
    )
    await upsert_book(db, _book_data("bk-rs-highest-internal-2020", "Highest Internal", 2.0, 4.5))


async def test_sort_rating_desc_prioritizes_internal_over_external(db):
    await _seed_list(db)
    items, _ = await list_books(db, genre=None, sort=BookSortEnum.rating_desc, page=1, limit=200)
    slugs = [b.slug for b in items]
    assert slugs.index("bk-rs-highest-internal-2020") < slugs.index(
        "bk-rs-low-external-high-internal-2020"
    )
    assert slugs.index("bk-rs-low-external-high-internal-2020") < slugs.index(
        "bk-rs-high-external-2020"
    )


async def test_sort_rating_asc_prioritizes_internal_over_external(db):
    """rating_internal ASC NULLS LAST: NULLs still sort last, not first —
    ascending only reorders the non-NULL values among themselves."""
    await _seed_list(db)
    items, _ = await list_books(db, genre=None, sort=BookSortEnum.rating_asc, page=1, limit=200)
    slugs = [b.slug for b in items]
    assert slugs.index("bk-rs-low-external-high-internal-2020") < slugs.index(
        "bk-rs-highest-internal-2020"
    )
    assert slugs.index("bk-rs-highest-internal-2020") < slugs.index("bk-rs-high-external-2020")


# ── Similar items (get_books_by_same_authors / get_books_by_genre_overlap) ──


async def test_similar_by_same_author_prioritizes_internal_over_external(db):
    source = await upsert_book(db, _book_data("bk-rs-author-source-2020", "Source Book", 5.0, None))
    low_ext_high_int = await upsert_book(
        db, _book_data("bk-rs-author-low-ext-high-int-2020", "Low Ext High Int", 1.0, 4.0)
    )
    high_ext_no_int = await upsert_book(
        db, _book_data("bk-rs-author-high-ext-no-int-2020", "High Ext No Int", 9.5, None)
    )

    author = await upsert_person(
        db,
        {
            "name": "RS Test Author",
            "slug": "rs-test-author-66",
            "profile_url": None,
            "last_synced_at": datetime.now(UTC),
        },
    )
    for book in (source, low_ext_high_int, high_ext_no_int):
        await upsert_credit(
            db,
            {
                "item_type": "BOOK",
                "item_id": book.id,
                "person_id": author.id,
                "role": "AUTHOR",
                "character_name": None,
                "billing_order": None,
            },
        )

    author_ids = await get_author_person_ids(db, source.id)
    results = await get_books_by_same_authors(db, author_ids, source.id, limit=10)
    slugs = [b.slug for b in results]
    assert slugs.index("bk-rs-author-low-ext-high-int-2020") < slugs.index(
        "bk-rs-author-high-ext-no-int-2020"
    )


async def test_similar_by_genre_overlap_prioritizes_internal_over_external(db):
    genre = [{"name": "bk-rs-genre-overlap", "slug": "bk-rs-genre-overlap"}]
    source = await upsert_book(
        db, _book_data("bk-rs-genre-source-2020", "Source Book", 5.0, None, genres=genre)
    )
    await upsert_book(
        db,
        _book_data("bk-rs-genre-low-ext-high-int-2020", "Low Ext High Int", 1.0, 4.0, genres=genre),
    )
    await upsert_book(
        db,
        _book_data("bk-rs-genre-high-ext-no-int-2020", "High Ext No Int", 9.5, None, genres=genre),
    )

    genre_ids = [g.id for g in source.genres]
    results = await get_books_by_genre_overlap(
        db, source.id, genre_ids, exclude_book_ids={source.id}, limit=10
    )
    slugs = [b.slug for b in results]
    assert slugs.index("bk-rs-genre-low-ext-high-int-2020") < slugs.index(
        "bk-rs-genre-high-ext-no-int-2020"
    )
