"""Scheduler setup — create and configure APScheduler with all sync jobs."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backlogg.scheduler.jobs import sync_books, sync_games, sync_movies, sync_series


def create_scheduler() -> AsyncIOScheduler:
    """Return a configured AsyncIOScheduler with all nightly sync jobs.

    Schedule (UTC):
      02:00 — movies
      02:30 — series
      03:00 — books
      03:30 — games
    """
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        sync_movies,
        trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="sync_movies",
        name="Nightly movie sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        sync_series,
        trigger=CronTrigger(hour=2, minute=30, timezone="UTC"),
        id="sync_series",
        name="Nightly series sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        sync_books,
        trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="sync_books",
        name="Nightly books sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        sync_games,
        trigger=CronTrigger(hour=3, minute=30, timezone="UTC"),
        id="sync_games",
        name="Nightly games sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    return scheduler
