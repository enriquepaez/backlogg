"""Cross-type catalog search, straight over the four content tables.

Only this file builds the search query.  There is no ``catalog_search``
materialized view any more (feature 91, issue #28): each of ``movies``,
``series``, ``books`` and ``games`` carries its own ``search_vector``
``GENERATED ALWAYS AS (...) STORED`` column with a GIN index over it, and the
cross-type result set is a ``UNION ALL`` of the four.

Two consequences worth stating out loud, because they are the whole point of
the change:

* **There is nothing to refresh.**  Postgres maintains a generated column
  inside the statement that writes the row, so a freshly ingested item is
  searchable the moment its transaction commits.  The old view needed
  ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` — a full second copy of 137 MB —
  after every ingestion, and that stopped fitting in Neon's 512 MB.
* **``ts_rank`` reads the stored column, never a recomputed expression.**
  ``func.ts_rank(model.search_vector, ...)`` and not
  ``ts_rank(to_tsvector(...), ...)``.  The second form would still pass every
  test in the suite while quietly recomputing the vector of every candidate
  row before the ``LIMIT``, which is exactly the cost this design pays 57 MB
  of disk to avoid (``progress/measure_91.md``).
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import String, func, literal, literal_column, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from backlogg.books.models import Book
from backlogg.games.models import Game
from backlogg.movies.models import Movie
from backlogg.series.models import Series
from backlogg.shared.search_vector import SEARCH_TS_CONFIG


@dataclass(frozen=True)
class _SearchSource:
    """One branch of the ``UNION ALL``.

    ``date_column`` is the part that is easy to get wrong: the retired view
    mapped four differently-named columns onto a single ``release_date``
    output — ``release_date`` for movies and games, ``first_air_date`` for
    series, ``first_publish_date`` for books.  Reproducing that mapping is not
    cosmetic: get it wrong and ``date_from``/``date_to`` stop filtering series
    and books with no error at all.
    """

    item_type: str
    model: type[DeclarativeBase]
    date_column: str


#: The four content tables, in the order the view listed them.
_SEARCH_SOURCES: tuple[_SearchSource, ...] = (
    _SearchSource("MOVIE", Movie, "release_date"),
    _SearchSource("SERIES", Series, "first_air_date"),
    _SearchSource("BOOK", Book, "first_publish_date"),
    _SearchSource("GAME", Game, "release_date"),
)

#: Same configuration the ``search_vector`` columns are built with.  A
#: mismatch here would silently match nothing.
_TS_CONFIG = literal_column(f"'{SEARCH_TS_CONFIG}'")


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        q: str | None,
        item_type: str | None = None,
        page: int = 1,
        limit: int = 20,
        date_from: date | None = None,
        date_to: date | None = None,
        rating_external_min: float | None = None,
        rating_external_max: float | None = None,
    ) -> tuple[list[dict], int]:
        """Search the catalog across all four content types.

        Returns (results, total) where results is a list of dicts and total is
        the count of matching rows (before pagination).

        When ``q`` is provided, uses plainto_tsquery so callers do not need to
        escape the query string, and results are ordered by
        ``rating_external DESC NULLS LAST`` first (best-rated matches surface
        above unrated/lower-rated ones, even when their ts_rank is lower),
        then by ts_rank descending as a tie-breaker among items with the same
        rating (including grouping all NULL-rating items together, ordered
        among themselves by text relevance), and finally by ``id`` as the
        last tie-breaker for pagination stability (issue #14). ts_rank alone
        is not a reliable primary sort key: distinct titles rarely produce
        identical ts_rank, so a rank-first order effectively never lets
        rating_external decide (issue #14 follow-up). When ``q`` is
        ``None`` this is a pure filter query
        (``date_from``/``date_to``/``rating_external_min/max``) — the
        full-text clause is omitted entirely (there is nothing to match
        against) and results are ordered by ``rating_external DESC NULLS
        LAST`` instead, since there is no rank to sort by.

        The tie-breaker chain ends with ``item_type`` after ``id``, which the
        materialized view did not need: ``id`` is unique *within* a content
        table but not across the four, so movie 7 and book 7 could otherwise
        swap places between two requests for the same page.  That is a strict
        refinement of the previous order — it only settles pairs whose
        relative order was undefined before — and it is what keeps issue #14's
        guarantee true now that the result set is a ``UNION ALL``.

        ``item_type`` prunes branches rather than filtering after the union:
        an unwanted content table is never read at all.
        """
        sources = _SEARCH_SOURCES
        if item_type is not None:
            wanted = item_type.upper()
            sources = tuple(s for s in _SEARCH_SOURCES if s.item_type == wanted)
            if not sources:
                # Unknown type: the same empty result the view's WHERE gave.
                return [], 0

        tsquery = None if q is None else func.plainto_tsquery(_TS_CONFIG, q)

        filters = {
            "tsquery": tsquery,
            "date_from": date_from,
            "date_to": date_to,
            "rating_external_min": rating_external_min,
            "rating_external_max": rating_external_max,
        }

        # Count first, on a union that selects a constant: the count must not
        # pay for ts_rank (it has no ORDER BY) nor for hauling the row payload.
        count_union = union_all(
            *(
                select(literal(1).label("one"))
                .select_from(source.model)
                .where(*_branch_filters(source, **filters))
                for source in sources
            )
        ).subquery()
        total_result = await self._session.execute(select(func.count()).select_from(count_union))
        total: int = total_result.scalar_one()

        rows_union = union_all(*(_row_branch(source, **filters) for source in sources)).subquery()

        order_by: list[Any] = [rows_union.c.rating_external.desc().nulls_last()]
        if tsquery is not None:
            order_by.append(rows_union.c.rank.desc())
        order_by.extend([rows_union.c.id, rows_union.c.item_type])

        paged_stmt = select(rows_union).order_by(*order_by).offset((page - 1) * limit).limit(limit)
        rows = (await self._session.execute(paged_stmt)).all()

        results = [
            {
                "id": row.id,
                "item_type": row.item_type,
                "slug": row.slug,
                "title": row.title,
                "overview": row.overview,
                "poster_url": row.poster_url,
                "release_date": row.release_date,
                "rating_external": (
                    float(row.rating_external) if row.rating_external is not None else None
                ),
                "rating_internal": (
                    float(row.rating_internal) if row.rating_internal is not None else None
                ),
            }
            for row in rows
        ]

        return results, total


def _branch_filters(
    source: _SearchSource,
    *,
    tsquery: Any | None,
    date_from: date | None,
    date_to: date | None,
    rating_external_min: float | None,
    rating_external_max: float | None,
) -> list[Any]:
    """WHERE clauses for one content table.

    The ``@@`` test goes against the stored ``search_vector``, which is what
    lets the per-table GIN index answer it.
    """
    model = source.model
    date_col = getattr(model, source.date_column)

    clauses: list[Any] = []
    if tsquery is not None:
        clauses.append(model.search_vector.bool_op("@@")(tsquery))
    if date_from is not None:
        clauses.append(date_col >= date_from)
    if date_to is not None:
        clauses.append(date_col <= date_to)
    if rating_external_min is not None:
        clauses.append(model.rating_external >= rating_external_min)
    if rating_external_max is not None:
        clauses.append(model.rating_external <= rating_external_max)
    return clauses


def _row_branch(source: _SearchSource, **filters: Any):
    """SELECT of one content table shaped like a row of the retired view.

    Column names and order are identical across the four branches — the
    ``UNION ALL`` matches by position, so a reordering here would mix
    ``poster_url`` into ``overview`` for one type only.  ``item_type`` is a
    per-branch literal, which is what makes pruning by type possible at all.

    ``rank`` is computed *inside* the branch so the tsvector never crosses the
    union boundary: what travels up is a float, not ~0,7 KB per candidate row.
    It is only selected when there is a query to rank against; without ``q``
    the column does not exist and nothing orders by it.
    """
    model = source.model
    tsquery = filters["tsquery"]

    columns: list[Any] = [
        model.id.label("id"),
        literal(source.item_type, type_=String).label("item_type"),
        model.slug.label("slug"),
        model.title.label("title"),
        model.overview.label("overview"),
        model.poster_url.label("poster_url"),
        getattr(model, source.date_column).label("release_date"),
        model.rating_external.label("rating_external"),
        model.rating_internal.label("rating_internal"),
    ]
    if tsquery is not None:
        columns.append(func.ts_rank(model.search_vector, tsquery).label("rank"))

    return select(*columns).select_from(model).where(*_branch_filters(source, **filters))
