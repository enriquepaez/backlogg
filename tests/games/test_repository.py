from datetime import UTC, date, datetime

from backlogg.games.repository import get_game_by_slug, upsert_game


def _game_data(slug: str, title: str = "Test Game") -> dict:
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": "A test game overview.",
        "release_date": date(2020, 3, 20),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 8.5,
        "rating_count_external": 1000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": "Action", "slug": "action"}],
        "platforms": [{"name": "PC (Microsoft Windows)", "slug": "win"}],
        "companies": [{"name": "CD Projekt Red", "slug": "cd-projekt-red", "role": "DEVELOPER"}],
    }


async def test_upsert_game(db):
    """Upsert a game and verify fields, genres, and platforms are persisted."""
    data = _game_data("test-game-2020-repo")
    game = await upsert_game(db, data)

    assert game.id is not None
    assert game.title == "Test Game"
    assert game.slug == "test-game-2020-repo"
    assert game.game_type == "MAIN_GAME"
    assert game.release_date == date(2020, 3, 20)
    assert len(game.genres) == 1
    assert game.genres[0].name == "Action"
    assert len(game.platforms) == 1
    assert game.platforms[0].slug == "win"


async def test_upsert_game_idempotent(db):
    """Upserting the same slug twice does not create a duplicate."""
    data1 = _game_data("idempotent-game-2020-repo", title="Original Title")
    game1 = await upsert_game(db, data1)

    data2 = _game_data("idempotent-game-2020-repo", title="Updated Title")
    game2 = await upsert_game(db, data2)

    assert game1.id == game2.id
    assert game2.title == "Updated Title"


async def test_get_game_by_slug_not_found(db):
    """Querying a non-existent slug returns None."""
    result = await get_game_by_slug(db, "slug-that-does-not-exist-game-9999")
    assert result is None


async def test_upsert_game_multiple_genres_and_platforms(db):
    """Upsert a game with multiple genres and platforms."""
    data = {
        "title": "The Witcher 3",
        "original_title": None,
        "slug": "the-witcher-3-wild-hunt-repo",
        "overview": "An epic RPG.",
        "release_date": date(2015, 5, 19),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 9.2,
        "rating_count_external": 5000,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [
            {"name": "Role-playing (RPG)", "slug": "role-playing-rpg"},
            {"name": "Adventure", "slug": "adventure"},
        ],
        "platforms": [
            {"name": "PC (Microsoft Windows)", "slug": "win"},
            {"name": "PlayStation 4", "slug": "ps4"},
        ],
        "companies": [],
    }
    game = await upsert_game(db, data)

    assert len(game.genres) == 2
    genre_names = {g.name for g in game.genres}
    assert "Role-playing (RPG)" in genre_names
    assert "Adventure" in genre_names

    assert len(game.platforms) == 2
    platform_slugs = {p.slug for p in game.platforms}
    assert "win" in platform_slugs
    assert "ps4" in platform_slugs
