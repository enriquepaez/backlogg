"""Repository tests for catalog search filters on books (feature 50).

Covers each new ``list_books`` filter individually (``search``, ``date_from``/
``date_to`` over ``first_publish_date``, ``rating_internal_min``/``max``,
``rating_external_min``/``max``) plus combinations with each other and with
the existing ``genre`` filter.
"""

from datetime import UTC, date, datetime

from backlogg.books.repository import list_books, upsert_book
from backlogg.books.schemas import BookSortEnum
from backlogg.shared.catalog_filters import CatalogSearchFilters


def _book_data(
    slug: str,
    title: str,
    first_publish_date: date | None,
    rating_external: float | None,
    rating_internal: float | None,
    genres: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "A test book overview.",
        "first_publish_date": first_publish_date,
        "original_language": "en",
        "poster_url": None,
        "rating_external": rating_external,
        "rating_count_external": 100,
        "rating_internal": rating_internal,
        "rating_count_internal": 5,
        "last_synced_at": datetime.now(UTC),
        "genres": genres or [],
    }


async def _seed(db):
    await upsert_book(
        db,
        _book_data(
            "filters-dune-book-1965",
            "Dune",
            date(1965, 8, 1),
            8.9,
            4.8,
            genres=[{"name": "bk-filters-scifi", "slug": "bk-filters-scifi"}],
        ),
    )
    await upsert_book(
        db,
        _book_data(
            "filters-dune-messiah-1969",
            "Dune Messiah",
            date(1969, 1, 1),
            7.5,
            4.0,
            genres=[{"name": "bk-filters-scifi", "slug": "bk-filters-scifi"}],
        ),
    )
    await upsert_book(
        db,
        _book_data(
            "filters-other-book-2000",
            "Some Other Book",
            date(2000, 1, 1),
            5.0,
            2.0,
            genres=[{"name": "bk-filters-drama", "slug": "bk-filters-drama"}],
        ),
    )


async def _slugs(db, filters: CatalogSearchFilters, genre: str | None = None) -> set[str]:
    items, _ = await list_books(
        db, genre=genre, sort=BookSortEnum.title_asc, page=1, limit=50, filters=filters
    )
    return {b.slug for b in items}


async def test_list_books_search_is_case_insensitive_substring(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(search="dUnE"))
    assert slugs == {"filters-dune-book-1965", "filters-dune-messiah-1969"}


async def test_list_books_date_range_on_first_publish_date(db):
    await _seed(db)
    slugs = await _slugs(
        db, CatalogSearchFilters(date_from=date(1960, 1, 1), date_to=date(1968, 1, 1))
    )
    assert slugs == {"filters-dune-book-1965"}


async def test_list_books_rating_internal_range(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(rating_internal_min=4.5, rating_internal_max=5.0))
    assert slugs == {"filters-dune-book-1965"}


async def test_list_books_rating_external_range(db):
    await _seed(db)
    slugs = await _slugs(
        db, CatalogSearchFilters(rating_external_min=7.0, rating_external_max=10.0)
    )
    assert slugs == {"filters-dune-book-1965", "filters-dune-messiah-1969"}


async def test_list_books_filters_combine_with_genre_and_each_other(db):
    await _seed(db)
    slugs = await _slugs(
        db,
        CatalogSearchFilters(search="dune", rating_internal_min=4.5),
        genre="bk-filters-scifi",
    )
    assert slugs == {"filters-dune-book-1965"}
