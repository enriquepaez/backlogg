from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backlogg.games.models import (
    Company,
    CompanyCredit,
    Game,
    GameGenre,
    GamePlatform,
    game_genres_join,
    game_platforms_join,
)
from backlogg.games.schemas import CompanyCreditOut, GameSortEnum
from backlogg.shared.bulk_load import BulkLoadSpec, EntityCreditSpec, LookupJoinSpec
from backlogg.shared.catalog_filters import CatalogSearchFilters, build_catalog_filter_clauses


async def list_games(
    db: AsyncSession,
    genre: str | None,
    sort: GameSortEnum,
    page: int,
    limit: int,
    filters: CatalogSearchFilters | None = None,
) -> tuple[list[Game], int]:
    """Return a paginated list of games with optional genre/search/date/rating filters and sorting.

    ``filters`` (feature 50) holds ``search``/``date_from``/``date_to``/
    ``rating_internal_min``/``rating_internal_max``/``rating_external_min``/
    ``rating_external_max`` — all independently optional and AND-combined
    with ``genre``. Returns a tuple of (items, total_count).
    """
    base_query = select(Game).options(selectinload(Game.genres), selectinload(Game.platforms))

    if genre is not None:
        base_query = base_query.join(Game.genres).where(GameGenre.slug == genre)

    if filters is not None:
        clauses = build_catalog_filter_clauses(
            filters,
            title_col=Game.title,
            date_col=Game.release_date,
            rating_internal_col=Game.rating_internal,
            rating_external_col=Game.rating_external,
        )
        if clauses:
            base_query = base_query.where(*clauses)

    # Count query (without pagination)
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Sorting. rating_desc/rating_asc order by rating_internal (the community's
    # own rating, feature 66) first — rating_external is only an internal
    # tie-break for items whose rating_internal is still NULL or tied, never
    # the primary/visible sort criterion.
    if sort == GameSortEnum.rating_desc:
        order_cols = (
            Game.rating_internal.desc().nulls_last(),
            Game.rating_external.desc().nulls_last(),
        )
    elif sort == GameSortEnum.rating_asc:
        order_cols = (
            Game.rating_internal.asc().nulls_last(),
            Game.rating_external.desc().nulls_last(),
        )
    elif sort == GameSortEnum.date_desc:
        order_cols = (Game.release_date.desc().nulls_last(),)
    elif sort == GameSortEnum.date_asc:
        order_cols = (Game.release_date.asc().nulls_last(),)
    else:  # title_asc
        order_cols = (Game.title.asc(),)

    base_query = base_query.order_by(*order_cols).offset((page - 1) * limit).limit(limit)
    result = await db.execute(base_query)
    items = list(result.scalars().unique().all())

    return items, total


async def get_company_credits_for_item(
    db: AsyncSession, item_type: str, item_id: int
) -> list[CompanyCreditOut]:
    """Return company credits (developer/publisher) for an item.

    Same read pattern as ``backlogg.shared.credits.get_credits_for_item``
    (join the credit row to its related entity, filter by item_type/item_id)
    applied to ``company_credits``/``companies`` instead of ``credits``/
    ``people`` — feature 67. Ordered by company name for a stable,
    human-friendly order (unlike person credits, company credits have no
    ``billing_order`` column). Empty list if the item has no company credits.
    """
    result = await db.execute(
        select(CompanyCredit, Company)
        .join(Company, CompanyCredit.company_id == Company.id)
        .where(CompanyCredit.item_type == item_type, CompanyCredit.item_id == item_id)
        .order_by(Company.name.asc())
    )
    rows = result.all()
    return [
        CompanyCreditOut(id=company.id, name=company.name, slug=company.slug, role=credit.role)
        for credit, company in rows
    ]


async def get_game_by_slug(db: AsyncSession, slug: str) -> Game | None:
    result = await db.execute(
        select(Game)
        .where(Game.slug == slug)
        .options(selectinload(Game.genres), selectinload(Game.platforms))
    )
    return result.scalar_one_or_none()


async def _get_or_create_genre(db: AsyncSession, name: str, slug: str) -> GameGenre:
    """Get or create a genre, treating the slug as its real identity.

    Look the slug up first: two name spellings that slugify to the same value
    must reuse the existing row instead of violating ``uq_game_genre_slug``.
    The name-conflict upsert remains as a fallback.
    """
    result = await db.execute(select(GameGenre).where(GameGenre.slug == slug))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    stmt = (
        pg_insert(GameGenre)
        .values(name=name, slug=slug)
        .on_conflict_do_update(
            constraint="uq_game_genre_name",
            set_={"slug": slug},
        )
        .returning(GameGenre.id)
    )
    result = await db.execute(stmt)
    genre_id = result.scalar_one()
    await db.flush()
    genre_result = await db.execute(select(GameGenre).where(GameGenre.id == genre_id))
    return genre_result.scalar_one()


async def _get_or_create_platform(db: AsyncSession, name: str, slug: str) -> GamePlatform:
    """Get or create a platform by slug — same collision-safe pattern as genres."""
    result = await db.execute(select(GamePlatform).where(GamePlatform.slug == slug))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    stmt = (
        pg_insert(GamePlatform)
        .values(name=name, slug=slug)
        .on_conflict_do_update(
            constraint="uq_game_platform_name",
            set_={"slug": slug},
        )
        .returning(GamePlatform.id)
    )
    result = await db.execute(stmt)
    platform_id = result.scalar_one()
    await db.flush()
    platform_result = await db.execute(select(GamePlatform).where(GamePlatform.id == platform_id))
    return platform_result.scalar_one()


async def _get_or_create_company(db: AsyncSession, name: str, slug: str) -> Company:
    result = await db.execute(select(Company).where(Company.slug == slug))
    company = result.scalar_one_or_none()
    if company is None:
        company = Company(name=name, slug=slug, last_synced_at=datetime.now(UTC))
        db.add(company)
        await db.flush()
    return company


async def upsert_game(db: AsyncSession, data: dict) -> Game:
    """Insert or update a game by slug.

    The ``data`` dict must contain all game fields plus optional lists:
    - ``genres``: list of dicts with ``name`` and ``slug``
    - ``platforms``: list of dicts with ``name`` and ``slug``
    - ``companies``: list of dicts with ``name``, ``slug``, and ``role``

    Per-field admin locks (feature 49 — catalog_manual_edit): any column
    listed in the existing row's ``locked_fields`` is excluded from the
    UPDATE, via a CASE per column inside the ON CONFLICT DO UPDATE statement
    that keeps the target row's own value when it is locked instead of the
    proposed (``excluded``) value. ``genres`` is not a plain column, so it is
    checked separately after the reload below, skipping the genre re-sync
    block when locked. ``platforms``/``companies`` are not admin-editable
    (see backlogg/admin/service.py's editable-field table) so they are never
    lockable and always sync normally.
    """
    genres_data: list[dict] = data.pop("genres", [])
    platforms_data: list[dict] = data.pop("platforms", [])
    companies_data: list[dict] = data.pop("companies", [])

    # Build INSERT ... ON CONFLICT (slug) DO UPDATE
    insert_stmt = pg_insert(Game).values(**data)
    set_ = {
        k: case(
            (Game.locked_fields.contains([k]), getattr(Game, k)),
            else_=getattr(insert_stmt.excluded, k),
        )
        for k in data
        if k not in ("id", "slug", "created_at", "rating_count_internal")
    }
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["slug"],
        set_=set_,
    ).returning(Game.id)
    result = await db.execute(stmt)
    game_id = result.scalar_one()
    await db.flush()

    # Expire stale identity-map entry
    for obj in db.identity_map.values():
        if isinstance(obj, Game) and obj.id == game_id:
            db.expire(obj)
            break

    # Reload full instance
    game_result = await db.execute(
        select(Game)
        .where(Game.id == game_id)
        .options(selectinload(Game.genres), selectinload(Game.platforms))
    )
    game = game_result.scalar_one()

    # ── Genres ──────────────────────────────────────────────────────────────
    if genres_data and "genres" not in game.locked_fields:
        genre_objects = []
        for g in genres_data:
            genre = await _get_or_create_genre(db, g["name"], g["slug"])
            genre_objects.append(genre)

        await db.execute(game_genres_join.delete().where(game_genres_join.c.game_id == game_id))
        for genre in genre_objects:
            await db.execute(game_genres_join.insert().values(game_id=game_id, genre_id=genre.id))
        await db.flush()
        await db.refresh(game, ["genres"])

    # ── Platforms ────────────────────────────────────────────────────────────
    if platforms_data:
        platform_objects = []
        for p in platforms_data:
            platform = await _get_or_create_platform(db, p["name"], p["slug"])
            platform_objects.append(platform)

        await db.execute(
            game_platforms_join.delete().where(game_platforms_join.c.game_id == game_id)
        )
        for platform in platform_objects:
            await db.execute(
                game_platforms_join.insert().values(game_id=game_id, platform_id=platform.id)
            )
        await db.flush()
        await db.refresh(game, ["platforms"])

    # ── Companies / company_credits ──────────────────────────────────────────
    if companies_data:
        for c in companies_data:
            company = await _get_or_create_company(db, c["name"], c["slug"])
            # Upsert company_credit
            credit_stmt = (
                pg_insert(CompanyCredit)
                .values(
                    item_type="GAME",
                    item_id=game_id,
                    company_id=company.id,
                    role=c["role"],
                )
                .on_conflict_do_nothing(
                    index_elements=["item_type", "item_id", "company_id", "role"]
                )
            )
            await db.execute(credit_stmt)
        await db.flush()

    return game


async def admin_update_game(db: AsyncSession, game: Game, updates: dict) -> Game:
    """Apply an admin backoffice edit (feature 49) to ``game`` in place.

    ``updates`` keys are a subset of the editable scalar columns (``title``,
    ``poster_url``, ``release_date``) plus an optional ``genres`` key holding
    a list of ``{"name", "slug"}`` dicts already resolved by the caller —
    same shape as ``upsert_game``'s ``genres_data``, so it reuses the same
    get-or-create + re-sync logic. ``platforms``/``companies`` are not
    admin-editable and are never touched here. Locked-fields bookkeeping is
    the caller's responsibility (backlogg/admin/service.py), not this
    function's.
    """
    genres_data = updates.pop("genres", None)

    for key, value in updates.items():
        setattr(game, key, value)

    if genres_data is not None:
        genre_objects = []
        for g in genres_data:
            genre = await _get_or_create_genre(db, g["name"], g["slug"])
            genre_objects.append(genre)

        await db.execute(game_genres_join.delete().where(game_genres_join.c.game_id == game.id))
        for genre in genre_objects:
            await db.execute(game_genres_join.insert().values(game_id=game.id, genre_id=genre.id))
        await db.flush()
        await db.refresh(game, ["genres"])

    await db.flush()
    return game


# ── Batch write path (feature 84) ─────────────────────────────────────────────


async def _bulk_fallback_upsert(db: AsyncSession, data: dict) -> Game:
    """Per-item fallback for the batch loader — resolves ``upsert_game`` late."""
    return await upsert_game(db, data)


GAME_BULK_SPEC = BulkLoadSpec(
    item_type="GAME",
    source="IGDB",
    table=Game.__table__,
    upsert_item=_bulk_fallback_upsert,
    lookups=(
        LookupJoinSpec(
            data_key="genres",
            lookup_table=GameGenre.__table__,
            lookup_columns=("name", "slug"),
            join_table=game_genres_join,
            item_column="game_id",
            lookup_column="genre_id",
        ),
        # Platforms are not admin-editable (see backlogg/admin/service.py's
        # editable-field table) so they are never lockable.
        LookupJoinSpec(
            data_key="platforms",
            lookup_table=GamePlatform.__table__,
            lookup_columns=("name", "slug"),
            join_table=game_platforms_join,
            item_column="game_id",
            lookup_column="platform_id",
            lockable=False,
        ),
    ),
    entity_credits=(
        EntityCreditSpec(
            data_key="companies",
            entity_table=Company.__table__,
            entity_columns=("name", "slug", "last_synced_at"),
            entity_defaults=(("last_synced_at", lambda: datetime.now(UTC)),),
            credit_table=CompanyCredit.__table__,
            entity_fk="company_id",
            constraint="uq_company_credit",
        ),
    ),
)
