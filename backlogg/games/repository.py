from datetime import UTC, datetime

from sqlalchemy import select
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


async def get_game_by_slug(db: AsyncSession, slug: str) -> Game | None:
    result = await db.execute(
        select(Game)
        .where(Game.slug == slug)
        .options(selectinload(Game.genres), selectinload(Game.platforms))
    )
    return result.scalar_one_or_none()


async def _get_or_create_genre(db: AsyncSession, name: str, slug: str) -> GameGenre:
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
    """
    genres_data: list[dict] = data.pop("genres", [])
    platforms_data: list[dict] = data.pop("platforms", [])
    companies_data: list[dict] = data.pop("companies", [])

    # Build INSERT ... ON CONFLICT (slug) DO UPDATE
    stmt = (
        pg_insert(Game)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["slug"],
            set_={
                k: v
                for k, v in data.items()
                if k not in ("id", "slug", "created_at", "rating_count_internal")
            },
        )
        .returning(Game.id)
    )
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
    if genres_data:
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
