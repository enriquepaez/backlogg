"""Recommendations repository — read-only DB queries.

Only this file imports and uses SQLAlchemy for the recommendations domain. It
reuses the polymorphic ``item_type``/``item_id`` model mapping from
``backlogg/ratings/repository.py`` (``ITEM_MODELS``) and the ``LibraryEntry`` /
``UserRating`` tables, and builds cross-type reads with the same ``union_all``
style as ``backlogg/feed/repository.py`` and ``backlogg/library/repository.py``.

Nothing here writes; recommendations are computed, never persisted. The one
thing this domain *does* persist — the semantic vectors of feature 75 — is
written from ``backlogg/shared/item_embeddings.py``, which owns that table the
way ``shared/item_relations.py`` owns its own. What lives here is the read half
of that job: which items are selected, and what text they are embedded from.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import String, and_, case, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from backlogg.books.models import Book, BookGenre, book_genres_join
from backlogg.games.models import Game, GameGenre, game_genres_join
from backlogg.library.models import LibraryEntry
from backlogg.movies.models import Movie, MovieGenre, movie_genres_join
from backlogg.ratings.models import UserRating
from backlogg.series.models import Series, SeriesGenre, series_genres_join
from backlogg.shared.credits import AUTHORSHIP_ROLES
from backlogg.shared.item_embeddings import ItemEmbedding
from backlogg.shared.models import Credit

#: Credit roles that mean "this person made it", for the diversification
#: penalty of feature 80. Authorship (the cross-type bridge) plus the two
#: roles that head a film and a series. ``WRITER`` is out for the same reason
#: ``AUTHORSHIP_ROLES`` leaves it out, and ``ACTOR`` is not a credit at all
#: since feature 89 — a shared supporting actor is not a shared saga.
DIVERSITY_CREATOR_ROLES: tuple[str, ...] = (*AUTHORSHIP_ROLES, "DIRECTOR", "CREATOR")

# Statuses that count as an implicit positive signal for seeding.
SEED_LIBRARY_STATUSES = ("completed", "want")
# Minimum explicit rating that counts as a seed.
SEED_MIN_SCORE = 4

# Per item_type: (content model, genre join table, join item-id column name,
# release-date column name). Mirrors library/repository._RELEASE_DATE_ATTR but
# also carries the many-to-many join needed for genre-overlap heuristics.
_TYPE_CONFIG: dict[str, tuple[type[DeclarativeBase], Any, str, str]] = {
    "MOVIE": (Movie, movie_genres_join, "movie_id", "release_date"),
    "SERIES": (Series, series_genres_join, "series_id", "first_air_date"),
    "BOOK": (Book, book_genres_join, "book_id", "first_publish_date"),
    "GAME": (Game, game_genres_join, "game_id", "release_date"),
}


def _release_col(item_type: str):
    model, _join, _item_col, release_attr = _TYPE_CONFIG[item_type]
    return getattr(model, release_attr)


async def get_seeds(db: AsyncSession, user_id: int, item_types: list[str]) -> list[Any]:
    """Return the user's seed items across ``item_types``, strongest first.

    A seed is any item the user rated with a score >= ``SEED_MIN_SCORE`` or has
    in their library with status in ``SEED_LIBRARY_STATUSES``. Each row carries
    ``item_type``, ``item_id``, ``slug``, ``title``, a numeric ``weight`` and a
    ``source`` ('rated' or 'library') so the service can build a human reason
    and prioritise stronger signals. Deduplicated per (item_type, item_id),
    keeping the highest-weight/ rated-over-library occurrence.
    """
    queries = []
    for item_type in item_types:
        model, _join, _item_col, _release_attr = _TYPE_CONFIG[item_type]

        rated = (
            select(
                literal(item_type, type_=String).label("item_type"),
                model.id.label("item_id"),
                model.slug.label("slug"),
                model.title.label("title"),
                UserRating.score.label("weight"),
                literal("rated", type_=String).label("source"),
            )
            .join(
                UserRating,
                and_(
                    UserRating.item_id == model.id,
                    UserRating.item_type == item_type,
                ),
            )
            .where(UserRating.user_id == user_id, UserRating.score >= SEED_MIN_SCORE)
        )

        library = (
            select(
                literal(item_type, type_=String).label("item_type"),
                model.id.label("item_id"),
                model.slug.label("slug"),
                model.title.label("title"),
                case((LibraryEntry.status == "completed", 4), else_=3).label("weight"),
                literal("library", type_=String).label("source"),
            )
            .join(
                LibraryEntry,
                and_(
                    LibraryEntry.item_id == model.id,
                    LibraryEntry.item_type == item_type,
                ),
            )
            .where(
                LibraryEntry.user_id == user_id,
                LibraryEntry.status.in_(SEED_LIBRARY_STATUSES),
            )
        )
        queries.append(rated)
        queries.append(library)

    combined = union_all(*queries) if len(queries) > 1 else queries[0]
    result = await db.execute(select(combined.subquery()))
    rows = list(result.all())

    # Order by strongest signal (higher weight, rated over library) and dedupe
    # per (item_type, item_id) keeping the first — done in Python so the same
    # item rated *and* in the library collapses to a single seed.
    rows.sort(key=lambda r: (-r.weight, 0 if r.source == "rated" else 1))
    seen: set[tuple[str, int]] = set()
    seeds = []
    for row in rows:
        key = (row.item_type, row.item_id)
        if key in seen:
            continue
        seen.add(key)
        seeds.append(row)
    return seeds


async def get_seen_item_ids(db: AsyncSession, user_id: int) -> set[tuple[str, int]]:
    """Return every (item_type, item_id) the user has rated or has in library.

    Used to exclude already-seen items from recommendations (regardless of
    score or status — any interaction counts as "seen").
    """
    result = await db.execute(
        select(UserRating.item_type, UserRating.item_id).where(UserRating.user_id == user_id)
    )
    seen = {(r.item_type, r.item_id) for r in result.all()}

    result = await db.execute(
        select(LibraryEntry.item_type, LibraryEntry.item_id).where(LibraryEntry.user_id == user_id)
    )
    seen |= {(r.item_type, r.item_id) for r in result.all()}
    return seen


async def get_seen_slugs(db: AsyncSession, user_id: int) -> set[str]:
    """Return the slugs of every item the user has rated or has in library.

    Slug-based exclusion for candidates that only expose a slug (e.g. the
    external similar-items results, which are not queried by id).
    """
    slugs: set[str] = set()
    for item_type, (model, _join, _item_col, _release_attr) in _TYPE_CONFIG.items():
        result = await db.execute(
            select(model.slug)
            .join(
                UserRating,
                and_(UserRating.item_id == model.id, UserRating.item_type == item_type),
            )
            .where(UserRating.user_id == user_id)
        )
        slugs |= {r[0] for r in result.all()}

        result = await db.execute(
            select(model.slug)
            .join(
                LibraryEntry,
                and_(LibraryEntry.item_id == model.id, LibraryEntry.item_type == item_type),
            )
            .where(LibraryEntry.user_id == user_id)
        )
        slugs |= {r[0] for r in result.all()}
    return slugs


async def get_genre_overlap_candidates(
    db: AsyncSession,
    item_type: str,
    seed_item_ids: list[int],
    excluded_item_ids: set[int],
    limit: int,
) -> list[Any]:
    """Local candidates that share a genre with the seeds, best overlap first.

    Heuristic used for books/games (no external similar API) and as the local
    candidate pool for movies/series before any external fan-out. Ranks by the
    number of shared genres, then external rating. Excludes the seeds
    themselves and anything already seen.
    """
    if not seed_item_ids:
        return []

    model, join, item_col, release_attr = _TYPE_CONFIG[item_type]
    join_item = join.c[item_col]
    release_col = getattr(model, release_attr)

    seed_genre_ids = select(join.c.genre_id).where(join_item.in_(seed_item_ids)).scalar_subquery()

    excluded = set(excluded_item_ids) | set(seed_item_ids)

    overlap = func.count(join.c.genre_id).label("overlap")
    stmt = (
        select(
            model.title.label("title"),
            model.slug.label("slug"),
            model.poster_url.label("poster_url"),
            release_col.label("release_date"),
            model.rating_external.label("rating_external"),
            model.rating_internal.label("rating_internal"),
            overlap,
        )
        .join(join, join_item == model.id)
        .where(join.c.genre_id.in_(seed_genre_ids))
        .where(model.id.notin_(excluded) if excluded else literal(True))
        .group_by(model.id)
        .order_by(overlap.desc(), model.rating_external.desc().nulls_last())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.all())


async def get_popular_items(
    db: AsyncSession,
    item_types: list[str],
    excluded_item_ids: set[tuple[str, int]],
    limit: int,
) -> list[Any]:
    """Cross-type popular fallback: highest community (internal) rating first.

    Used when the user has no seeds. Excludes items the user has already
    seen. ``rating_internal`` decides the order (feature 66 — the
    community's own rating); ``rating_external`` is only an internal
    tie-break for items whose ``rating_internal`` is still NULL or tied.
    The pre-existing ``rating_external IS NOT NULL`` filter is unchanged —
    it still requires *some* rating signal to qualify as "popular" among
    items with no ratings at all yet, it does not decide the order.
    Returns rows with
    item_type/title/slug/poster_url/release_date/rating_external.
    """
    queries = []
    for item_type in item_types:
        model, _join, _item_col, _release_attr = _TYPE_CONFIG[item_type]
        release_col = _release_col(item_type)
        excluded_ids = [iid for (it, iid) in excluded_item_ids if it == item_type]
        q = select(
            literal(item_type, type_=String).label("item_type"),
            model.title.label("title"),
            model.slug.label("slug"),
            model.poster_url.label("poster_url"),
            release_col.label("release_date"),
            model.rating_internal.label("rating_internal"),
            model.rating_external.label("rating_external"),
        ).where(model.rating_external.is_not(None))
        if excluded_ids:
            q = q.where(model.id.notin_(excluded_ids))
        queries.append(q)

    combined = union_all(*queries) if len(queries) > 1 else queries[0]
    subq = combined.subquery()
    stmt = (
        select(subq)
        .order_by(
            subq.c.rating_internal.desc().nulls_last(),
            subq.c.rating_external.desc().nulls_last(),
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.all())


async def get_authorship_works(
    db: AsyncSession,
    person_id: int,
    *,
    exclude: tuple[str, int] | None = None,
    limit: int | None = None,
) -> list[Any]:
    """Return every catalog work this person authored, across all item types.

    Layer 0 of ``docs/recommendations-plan.md``: ``AUTHOR`` (books) and
    ``SOURCE_AUTHOR`` (the film/series adapted from a prior work) are treated
    as **one** authorship class — ``AUTHORSHIP_ROLES`` — so one call from
    either shore returns the other. ``WRITER`` is not authorship and never
    appears here.

    The anti-translator gate: TMDB credits translators with ``job: "Book"``
    (*The Witcher* credits Danusia Stok and David French alongside Sapkowski)
    and the job does not tell them apart, so the whole result is conditioned on
    the person also holding an ``AUTHOR`` credit on a book **that exists in the
    catalog**. A translator has ``SOURCE_AUTHOR`` credits and no book of their
    own, so they get an empty list instead of a bogus bridge.

    ``exclude`` drops the ``(item_type, item_id)`` the caller started from.
    Rows carry item_type/item_id/title/slug/role, ordered by type then id.
    Every item type is covered; ``GAME`` contributes nothing because games
    carry no person credits at all (decision of 2026-09-04, docs/schema.md).
    """
    # Gate, evaluated once for the whole statement: does this person have an
    # AUTHOR credit on a book in the catalog?
    authored_a_book = (
        # ``Credit.person_id`` and not ``Credit.id``: feature 89 dropped the
        # surrogate key.  Inside an EXISTS the projection is irrelevant.
        select(Credit.person_id)
        .join(Book, Book.id == Credit.item_id)
        .where(
            Credit.person_id == person_id,
            Credit.item_type == "BOOK",
            Credit.role == "AUTHOR",
        )
        .exists()
    )

    queries = []
    for item_type, (model, _join, _item_col, _release_attr) in _TYPE_CONFIG.items():
        q = (
            select(
                literal(item_type, type_=String).label("item_type"),
                model.id.label("item_id"),
                model.title.label("title"),
                model.slug.label("slug"),
                Credit.role.label("role"),
            )
            .select_from(model)
            .join(Credit, and_(Credit.item_id == model.id, Credit.item_type == item_type))
            .where(Credit.person_id == person_id, Credit.role.in_(AUTHORSHIP_ROLES))
        )
        if exclude is not None and exclude[0] == item_type:
            q = q.where(model.id != exclude[1])
        queries.append(q)

    subq = union_all(*queries).subquery()
    stmt = select(subq).where(authored_a_book).order_by(subq.c.item_type, subq.c.item_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.all())


@dataclass(frozen=True, slots=True)
class ItemRef:
    """The minimum needed to link to a catalog item from another item's page.

    ``item_type`` is part of the value and not of the caller's context on
    purpose — see ``AdaptationOut`` in ``schemas.py`` for why.
    """

    item_type: str
    item_id: int
    slug: str
    title: str
    poster_url: str | None


async def get_item_refs(
    db: AsyncSession, keys: Iterable[tuple[str, int]]
) -> dict[tuple[str, int], ItemRef]:
    """Resolve ``(item_type, item_id)`` pairs to their linkable catalog row.

    One query per distinct ``item_type`` present (at most four), not one per
    key: the far ends of an item's adaptation edges are a handful of rows
    spread over two or three tables.

    A key with no row is simply **absent** from the result. ``item_relations``
    has no foreign keys — the reference is polymorphic, like ``external_ids``
    and ``credits``, and integrity is the application's job
    (``docs/conventions.md``) — so an edge can outlive the item at its far end.
    The caller drops those edges; the alternative would be an entry whose link
    is guaranteed to 404.
    """
    ids_by_type: dict[str, set[int]] = {}
    for item_type, item_id in keys:
        if item_type in _TYPE_CONFIG:
            ids_by_type.setdefault(item_type, set()).add(item_id)

    refs: dict[tuple[str, int], ItemRef] = {}
    for item_type, item_ids in ids_by_type.items():
        model, _join, _item_col, _release_attr = _TYPE_CONFIG[item_type]
        result = await db.execute(
            select(model.id, model.slug, model.title, model.poster_url).where(
                model.id.in_(item_ids)
            )
        )
        for row in result.all():
            refs[(item_type, row.id)] = ItemRef(
                item_type=item_type,
                item_id=row.id,
                slug=row.slug,
                title=row.title,
                poster_url=row.poster_url,
            )
    return refs


# ── Semantic layer: which items get a vector, and from what text (feature 75) ─

# Per item_type, the genre vocabulary table that hangs off the join in
# ``_TYPE_CONFIG``. Separate from ``_TYPE_CONFIG`` because the four vocabularies
# are four different tables (books use the controlled vocabulary of feature 72),
# and no other consumer in this file needs the genre *name*.
_GENRE_MODELS: dict[str, type[DeclarativeBase]] = {
    "MOVIE": MovieGenre,
    "SERIES": SeriesGenre,
    "BOOK": BookGenre,
    "GAME": GameGenre,
}


@dataclass(frozen=True, slots=True)
class EmbeddingSource:
    """Everything one item contributes to its vector, plus what is stored today.

    ``stored_model`` / ``stored_hash`` come from a LEFT JOIN against
    ``item_embeddings`` in the same query rather than a second round trip: they
    are what decides whether this item needs re-embedding at all, and fetching
    them separately would double the reads of a job whose whole point is that
    almost every item is skipped.
    """

    item_type: str
    item_id: int
    title: str
    original_title: str | None
    overview: str | None
    genres: tuple[str, ...]
    stored_model: str | None
    stored_hash: str | None


def _embedding_rank_order(model: type[DeclarativeBase]):
    """The selection order of the bounded subset, and the whole of the criterion.

    Three keys, in this order:

    1. **Has a synopsis.** An item with only a title and genres still produces
       a vector, but a thin one; when the budget is capped, spending it on
       items the model has something to read about is strictly better. This
       matters most for books, where Open Library describes a minority of works.
    2. **``rating_count_external`` descending.** How many people rated the item
       at its own source: the closest thing to a notoriety signal that all four
       types carry. Compared only *within* a type — a TMDB vote count and an
       IGDB rating count are not the same unit, which is exactly why the cap is
       split into per-type quotas instead of being one global ranking.
    3. **``rating_external`` descending, then ``id`` ascending.** Tie-breakers.
       ``id`` last makes the order total and therefore the whole selection
       deterministic, which is what lets an interrupted run resume by simply
       recomputing the list.

    Books deserve a note: Open Library reports no rating counts at all today,
    so for that type keys 2 and 3 are flat and the order is effectively "has a
    synopsis, then seed order". That is acceptable rather than accidental —
    every work in the book catalog already cleared the reading-log and edition
    thresholds of ``docs/seeding-plan.md`` before being seeded, so the type has
    no long tail of unknown items to filter out in the first place.
    """
    overview_col = model.overview
    return (
        case((and_(overview_col.is_not(None), overview_col != ""), 1), else_=0).desc(),
        func.coalesce(model.rating_count_external, 0).desc(),
        func.coalesce(model.rating_external, 0).desc(),
        model.id.asc(),
    )


async def count_catalog_items(db: AsyncSession, item_type: str) -> int:
    """How many items of this type exist — the ceiling on its quota."""
    model, _join, _item_col, _release_attr = _TYPE_CONFIG[item_type]
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


async def select_embedding_candidate_ids(db: AsyncSession, item_type: str, limit: int) -> list[int]:
    """The ``limit`` best-signalled items of this type, in selection order.

    Returned as a plain id list, computed once at the start of a run, rather
    than paged through with OFFSET: the list for a whole type is at most tens
    of thousands of integers, and materialising it once means the expensive
    ordering is paid once instead of once per batch — and that every batch sees
    the *same* ranking, which an OFFSET walk over a table being written to by
    the nightly sync would not guarantee.
    """
    if limit <= 0:
        return []
    model, _join, _item_col, _release_attr = _TYPE_CONFIG[item_type]
    stmt = select(model.id).order_by(*_embedding_rank_order(model)).limit(limit)
    result = await db.execute(stmt)
    return [int(row) for row in result.scalars().all()]


async def load_embedding_sources(
    db: AsyncSession, item_type: str, item_ids: Sequence[int]
) -> list[EmbeddingSource]:
    """Title, genres, synopsis and current vector state for a batch of ids.

    Genres are aggregated in SQL (``array_agg`` ordered by name) instead of
    through the ORM relationship: the serialised text has to be **byte-stable**
    across runs or its hash changes and every item is re-embedded for nothing,
    and a deterministic ``ORDER BY`` inside the aggregate is the cheapest way to
    guarantee that.

    Rows come back in the order the caller asked for, not the database's:
    ``item_ids`` is a slice of the ranked selection and the caller reports
    progress against it.
    """
    if not item_ids:
        return []
    model, join_table, item_col, _release_attr = _TYPE_CONFIG[item_type]
    genre_model = _GENRE_MODELS[item_type]
    join_item_col = join_table.c[item_col]

    genres_subq = (
        select(func.array_agg(aggregate_order_by(genre_model.name, genre_model.name.asc())))
        .select_from(join_table)
        .join(genre_model, genre_model.id == join_table.c.genre_id)
        .where(join_item_col == model.id)
        .correlate(model)
        .scalar_subquery()
    )
    stmt = (
        select(
            model.id,
            model.title,
            model.original_title,
            model.overview,
            genres_subq.label("genres"),
            ItemEmbedding.model.label("stored_model"),
            ItemEmbedding.source_hash.label("stored_hash"),
        )
        .outerjoin(
            ItemEmbedding,
            and_(
                ItemEmbedding.item_type == item_type,
                ItemEmbedding.item_id == model.id,
            ),
        )
        .where(model.id.in_(list(item_ids)))
    )
    result = await db.execute(stmt)
    by_id = {
        int(row.id): EmbeddingSource(
            item_type=item_type,
            item_id=int(row.id),
            title=row.title,
            original_title=row.original_title,
            overview=row.overview,
            genres=tuple(row.genres or ()),
            stored_model=row.stored_model,
            stored_hash=row.stored_hash,
        )
        for row in result.all()
    }
    return [by_id[item_id] for item_id in item_ids if item_id in by_id]


# ── Semantic /similar: hydrating the neighbours the HNSW index returned (80) ──


@dataclass(frozen=True, slots=True)
class SimilarCandidateRow:
    """A neighbour, with everything both the ranker and the response need.

    One shape for the four types: the semantic neighbours of a film are a mix
    of films, series, books and games, so a per-type row would have to be
    merged back together by the caller anyway. ``release_date`` is the type's
    own date column (``first_air_date`` for series, ``first_publish_date`` for
    books), already normalised here so the service never branches on type.
    """

    item_type: str
    item_id: int
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    rating_internal: float | None
    creator_ids: frozenset[int]


async def get_similar_candidates(
    db: AsyncSession, keys: Iterable[tuple[str, int]]
) -> dict[tuple[str, int], SimilarCandidateRow]:
    """Resolve ``(item_type, item_id)`` neighbours to displayable rows.

    At most five queries for a whole ``/similar`` response: one per distinct
    ``item_type`` present (four at the very most) plus **one** over ``credits``
    for every key at once. The credits read is batched across types rather than
    folded into each type's query because it is the same table for all four and
    a correlated aggregate per type would turn one index scan into four.

    ``creator_ids`` is the diversification signal of ``ranking.py``: the people
    who *made* the item — ``AUTHOR``/``SOURCE_AUTHOR`` (authorship, the
    cross-type bridge of layer 0), plus ``DIRECTOR`` and ``CREATOR``.
    ``WRITER`` is excluded for the same reason ``AUTHORSHIP_ROLES`` excludes it
    and ``ACTOR`` is not there at all — it lives in ``item_cast`` since feature
    89, and two films sharing a supporting actor are not "the same saga".

    A key with no row is **absent** from the result, exactly like
    ``get_item_refs``: ``item_embeddings`` has no foreign keys either, so a
    vector can outlive the item it described until the next generation. The
    caller drops those instead of emitting a link that is guaranteed to 404.
    """
    ids_by_type: dict[str, set[int]] = {}
    for item_type, item_id in keys:
        if item_type in _TYPE_CONFIG:
            ids_by_type.setdefault(item_type, set()).add(item_id)
    if not ids_by_type:
        return {}

    creators: dict[tuple[str, int], set[int]] = {}
    credit_filters = [
        and_(Credit.item_type == item_type, Credit.item_id.in_(item_ids))
        for item_type, item_ids in ids_by_type.items()
    ]
    credit_rows = await db.execute(
        select(Credit.item_type, Credit.item_id, Credit.person_id).where(
            Credit.role.in_(DIVERSITY_CREATOR_ROLES), or_(*credit_filters)
        )
    )
    for row in credit_rows.all():
        creators.setdefault((row.item_type, row.item_id), set()).add(int(row.person_id))

    rows: dict[tuple[str, int], SimilarCandidateRow] = {}
    for item_type, item_ids in ids_by_type.items():
        model, _join, _item_col, _release_attr = _TYPE_CONFIG[item_type]
        release_col = _release_col(item_type)
        result = await db.execute(
            select(
                model.id,
                model.title,
                model.slug,
                model.poster_url,
                release_col.label("release_date"),
                model.rating_external,
                model.rating_internal,
            ).where(model.id.in_(item_ids))
        )
        for row in result.all():
            key = (item_type, int(row.id))
            rows[key] = SimilarCandidateRow(
                item_type=item_type,
                item_id=int(row.id),
                title=row.title,
                slug=row.slug,
                poster_url=row.poster_url,
                release_date=row.release_date,
                rating_external=(
                    float(row.rating_external) if row.rating_external is not None else None
                ),
                rating_internal=(
                    float(row.rating_internal) if row.rating_internal is not None else None
                ),
                creator_ids=frozenset(creators.get(key, ())),
            )
    return rows
