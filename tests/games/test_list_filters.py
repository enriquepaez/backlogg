"""Repository tests for catalog search filters on games (feature 50).

Covers each new ``list_games`` filter individually (``search``, ``date_from``/
``date_to`` over ``release_date``, ``rating_internal_min``/``max``,
``rating_external_min``/``max``) plus combinations with each other and with
the existing ``genre`` filter.
"""

from datetime import UTC, date, datetime

from backlogg.games.repository import list_games, upsert_game
from backlogg.games.schemas import GameSortEnum
from backlogg.shared.catalog_filters import CatalogSearchFilters


def _game_data(
    slug: str,
    title: str,
    release_date: date | None,
    rating_external: float | None,
    rating_internal: float | None,
    genres: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "A test game overview.",
        "release_date": release_date,
        "game_type": "main_game",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": rating_external,
        "rating_count_external": 100,
        "rating_internal": rating_internal,
        "rating_count_internal": 5,
        "last_synced_at": datetime.now(UTC),
        "genres": genres or [],
        "platforms": [],
        "companies": [],
    }


async def _seed(db):
    await upsert_game(
        db,
        _game_data(
            "filters-doom-1993",
            "Doom",
            date(1993, 12, 10),
            8.5,
            4.5,
            genres=[{"name": "gm-filters-shooter", "slug": "gm-filters-shooter"}],
        ),
    )
    await upsert_game(
        db,
        _game_data(
            "filters-doom-eternal-2020",
            "Doom Eternal",
            date(2020, 3, 20),
            8.9,
            4.7,
            genres=[{"name": "gm-filters-shooter", "slug": "gm-filters-shooter"}],
        ),
    )
    await upsert_game(
        db,
        _game_data(
            "filters-other-game-2010",
            "Some Other Game",
            date(2010, 1, 1),
            5.0,
            2.0,
            genres=[{"name": "gm-filters-puzzle", "slug": "gm-filters-puzzle"}],
        ),
    )


async def _slugs(db, filters: CatalogSearchFilters, genre: str | None = None) -> set[str]:
    items, _ = await list_games(
        db, genre=genre, sort=GameSortEnum.title_asc, page=1, limit=50, filters=filters
    )
    return {g.slug for g in items}


async def test_list_games_search_is_case_insensitive_substring(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(search="dOOm"))
    assert slugs == {"filters-doom-1993", "filters-doom-eternal-2020"}


async def test_list_games_date_range_on_release_date(db):
    await _seed(db)
    slugs = await _slugs(
        db, CatalogSearchFilters(date_from=date(2015, 1, 1), date_to=date(2021, 1, 1))
    )
    assert slugs == {"filters-doom-eternal-2020"}


async def test_list_games_rating_internal_range(db):
    await _seed(db)
    slugs = await _slugs(db, CatalogSearchFilters(rating_internal_min=4.6, rating_internal_max=5.0))
    assert slugs == {"filters-doom-eternal-2020"}


async def test_list_games_rating_external_range(db):
    await _seed(db)
    slugs = await _slugs(
        db, CatalogSearchFilters(rating_external_min=8.0, rating_external_max=10.0)
    )
    assert slugs == {"filters-doom-1993", "filters-doom-eternal-2020"}


async def test_list_games_filters_combine_with_genre_and_each_other(db):
    await _seed(db)
    slugs = await _slugs(
        db,
        CatalogSearchFilters(search="doom", rating_internal_min=4.6),
        genre="gm-filters-shooter",
    )
    assert slugs == {"filters-doom-eternal-2020"}
