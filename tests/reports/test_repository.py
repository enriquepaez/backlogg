"""Repository tests for backlogg/reports/repository.py.

Runs against the real Postgres test DB (no mocks) per docs/conventions.md.
"""

from datetime import UTC, datetime

from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import upsert_rating
from backlogg.reports.repository import (
    create_report_if_not_exists,
    get_report_by_id,
    list_reports,
    resolve_report,
)
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Report Repo Movie") -> dict:
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": "overview",
        "release_date": None,
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": None,
        "rating_count_external": None,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


async def _make_user(db, username: str) -> int:
    user = await create_user(
        db,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password_hash": "hash",
            "display_name": username,
        },
    )
    return user.id


async def _make_review(db, slug: str, author_id: int) -> int:
    movie = await upsert_movie(db, _movie_data(slug))
    rating = await upsert_rating(
        db,
        user_id=author_id,
        item_type="MOVIE",
        item_id=movie.id,
        score=5,
        review_text="a review",
    )
    return rating.id


# ── create_report_if_not_exists ──────────────────────────────────────────


async def test_create_report_inserts_row(db):
    author = await _make_user(db, "report-repo-author-1")
    reporter = await _make_user(db, "report-repo-reporter-1")
    rating_id = await _make_review(db, "report-repo-movie-1", author)

    report, created = await create_report_if_not_exists(
        db, reporter_id=reporter, rating_id=rating_id, reason="spam"
    )

    assert created is True
    assert report.reporter_id == reporter
    assert report.rating_id == rating_id
    assert report.reason == "spam"
    assert report.status == "open"
    assert report.resolved_at is None


async def test_create_report_is_idempotent_per_pair(db):
    author = await _make_user(db, "report-repo-author-2")
    reporter = await _make_user(db, "report-repo-reporter-2")
    rating_id = await _make_review(db, "report-repo-movie-2", author)

    first, created_first = await create_report_if_not_exists(
        db, reporter_id=reporter, rating_id=rating_id, reason="spam"
    )
    second, created_second = await create_report_if_not_exists(
        db, reporter_id=reporter, rating_id=rating_id, reason="different reason"
    )

    assert created_first is True
    assert created_second is False
    # Same row returned; original reason preserved (no overwrite on repeat).
    assert second.id == first.id
    assert second.reason == "spam"

    _, total = await list_reports(db, status=None, page=1, limit=50)
    assert total >= 1


async def test_two_reporters_same_review_are_distinct(db):
    author = await _make_user(db, "report-repo-author-3")
    r1 = await _make_user(db, "report-repo-reporter-3a")
    r2 = await _make_user(db, "report-repo-reporter-3b")
    rating_id = await _make_review(db, "report-repo-movie-3", author)

    rep1, c1 = await create_report_if_not_exists(
        db, reporter_id=r1, rating_id=rating_id, reason=None
    )
    rep2, c2 = await create_report_if_not_exists(
        db, reporter_id=r2, rating_id=rating_id, reason=None
    )

    assert c1 is True and c2 is True
    assert rep1.id != rep2.id


# ── list_reports ─────────────────────────────────────────────────────────


async def test_list_reports_filters_by_status(db):
    author = await _make_user(db, "report-repo-author-4")
    reporter = await _make_user(db, "report-repo-reporter-4")
    rating_id = await _make_review(db, "report-repo-movie-4", author)

    report, _ = await create_report_if_not_exists(
        db, reporter_id=reporter, rating_id=rating_id, reason="x"
    )

    open_reports, _ = await list_reports(db, status="open", page=1, limit=50)
    assert any(r.id == report.id for r in open_reports)

    resolved_reports, _ = await list_reports(db, status="resolved", page=1, limit=50)
    assert all(r.id != report.id for r in resolved_reports)


async def test_list_reports_paginates(db):
    author = await _make_user(db, "report-repo-author-5")
    rating_id = await _make_review(db, "report-repo-movie-5", author)
    for i in range(3):
        reporter = await _make_user(db, f"report-repo-reporter-5-{i}")
        await create_report_if_not_exists(
            db, reporter_id=reporter, rating_id=rating_id, reason=None
        )

    page1, total = await list_reports(db, status=None, page=1, limit=2)
    assert total >= 3
    assert len(page1) == 2


# ── resolve_report ───────────────────────────────────────────────────────


async def test_resolve_report_marks_resolved(db):
    author = await _make_user(db, "report-repo-author-6")
    reporter = await _make_user(db, "report-repo-reporter-6")
    rating_id = await _make_review(db, "report-repo-movie-6", author)

    report, _ = await create_report_if_not_exists(
        db, reporter_id=reporter, rating_id=rating_id, reason=None
    )

    resolved = await resolve_report(db, report)
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None

    fetched = await get_report_by_id(db, report.id)
    assert fetched is not None
    assert fetched.status == "resolved"
