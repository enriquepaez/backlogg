import re
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backlogg.core.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    """Create an async engine, handling asyncpg's SSL requirements.

    asyncpg does not accept 'sslmode' as a query parameter.  When the URL
    contains ``?sslmode=require`` (Neon-style), we strip it and pass
    ``ssl=True`` via connect_args instead.
    """
    connect_args: dict = {}
    if "sslmode" in url:
        url = re.sub(r"[?&]sslmode=\w+", "", url)
        connect_args["ssl"] = True
    return create_async_engine(url, echo=False, connect_args=connect_args)


engine = _make_engine(settings.DATABASE_URL)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
