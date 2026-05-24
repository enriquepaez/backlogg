import asyncio
import os
import re
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

# Import all models so Alembic can detect them
import backlogg.shared.external_ids  # noqa: F401
import backlogg.shared.models  # noqa: F401
from alembic import context
from backlogg.core.database import Base  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_engine_args() -> tuple[str, dict]:
    """Return (clean_url, connect_args) for the current environment.

    Priority:
    1. DATABASE_URL os env var (set by conftest when running tests)
    2. settings.DATABASE_URL (reads from .env via pydantic-settings)
    """
    # Inline import to avoid circular import issues during alembic startup
    if "DATABASE_URL" in os.environ:
        url = os.environ["DATABASE_URL"]
    else:
        from backlogg.core.config import settings

        url = settings.DATABASE_URL

    connect_args: dict = {}
    if "sslmode" in url:
        url = re.sub(r"[?&]sslmode=\w+", "", url)
        connect_args["ssl"] = True
    return url, connect_args


def run_migrations_offline() -> None:
    url, _ = _get_engine_args()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, connect_args = _get_engine_args()
    connectable = create_async_engine(url, connect_args=connect_args)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
