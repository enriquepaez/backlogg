from sqlalchemy import String, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.books.models import BookGenre, book_genres_join
from backlogg.games.models import GameGenre, game_genres_join
from backlogg.genres.schemas import GenreWithCountOut
from backlogg.movies.models import MovieGenre, movie_genres_join
from backlogg.series.models import SeriesGenre, series_genres_join


async def list_genres(
    db: AsyncSession,
    item_type: str | None,
) -> list[GenreWithCountOut]:
    """Return genres with item counts, optionally filtered by item_type.

    Each row includes name, slug, item_type label, and COUNT of associated items.
    """
    queries = []

    if item_type is None or item_type == "movie":
        movie_q = (
            select(
                MovieGenre.name.label("name"),
                MovieGenre.slug.label("slug"),
                literal("movie", type_=String).label("item_type"),
                func.count(movie_genres_join.c.movie_id).label("count"),
            )
            .outerjoin(movie_genres_join, MovieGenre.id == movie_genres_join.c.genre_id)
            .group_by(MovieGenre.id, MovieGenre.name, MovieGenre.slug)
        )
        queries.append(movie_q)

    if item_type is None or item_type == "series":
        series_q = (
            select(
                SeriesGenre.name.label("name"),
                SeriesGenre.slug.label("slug"),
                literal("series", type_=String).label("item_type"),
                func.count(series_genres_join.c.series_id).label("count"),
            )
            .outerjoin(series_genres_join, SeriesGenre.id == series_genres_join.c.genre_id)
            .group_by(SeriesGenre.id, SeriesGenre.name, SeriesGenre.slug)
        )
        queries.append(series_q)

    if item_type is None or item_type == "book":
        book_q = (
            select(
                BookGenre.name.label("name"),
                BookGenre.slug.label("slug"),
                literal("book", type_=String).label("item_type"),
                func.count(book_genres_join.c.book_id).label("count"),
            )
            .outerjoin(book_genres_join, BookGenre.id == book_genres_join.c.genre_id)
            .group_by(BookGenre.id, BookGenre.name, BookGenre.slug)
        )
        queries.append(book_q)

    if item_type is None or item_type == "game":
        game_q = (
            select(
                GameGenre.name.label("name"),
                GameGenre.slug.label("slug"),
                literal("game", type_=String).label("item_type"),
                func.count(game_genres_join.c.game_id).label("count"),
            )
            .outerjoin(game_genres_join, GameGenre.id == game_genres_join.c.genre_id)
            .group_by(GameGenre.id, GameGenre.name, GameGenre.slug)
        )
        queries.append(game_q)

    if len(queries) == 1:
        final_query = queries[0]
    else:
        final_query = union_all(*queries)

    result = await db.execute(final_query)
    rows = result.all()

    return [
        GenreWithCountOut(
            name=row.name,
            slug=row.slug,
            item_type=row.item_type,
            count=row.count,
        )
        for row in rows
    ]
