"""Service tests for backlogg/reports/service.py.

No external adapter to mock — runs against the real test DB.
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from backlogg.movies.repository import upsert_movie
from backlogg.ratings.repository import upsert_rating
from backlogg.reports import service
from backlogg.users.repository import create_user


def _movie_data(slug: str, title: str = "Report Svc Movie") -> dict:
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


# ── report_review ────────────────────────────────────────────────────────


async def test_report_review_creates_report(db):
    author = await _make_user(db, "report-svc-author-1")
    reporter = await _make_user(db, "report-svc-reporter-1")
    rating_id = await _make_review(db, "report-svc-movie-1", author)

    report, created = await service.report_review(
        db, rating_id=rating_id, reason="spam", reporter_id=reporter
    )

    assert created is True
    assert report.rating_id == rating_id
    assert report.reporter_id == reporter
    assert report.status == "open"


async def test_report_review_is_idempotent(db):
    author = await _make_user(db, "report-svc-author-2")
    reporter = await _make_user(db, "report-svc-reporter-2")
    rating_id = await _make_review(db, "report-svc-movie-2", author)

    first, created_first = await service.report_review(
        db, rating_id=rating_id, reason="spam", reporter_id=reporter
    )
    second, created_second = await service.report_review(
        db, rating_id=rating_id, reason="again", reporter_id=reporter
    )

    assert created_first is True
    assert created_second is False
    assert second.id == first.id


async def test_report_unknown_review_raises_404(db):
    reporter = await _make_user(db, "report-svc-reporter-3")

    with pytest.raises(HTTPException) as exc:
        await service.report_review(db, rating_id=999_999_999, reason=None, reporter_id=reporter)
    assert exc.value.status_code == 404


# ── resolve_report ───────────────────────────────────────────────────────


async def test_resolve_report_marks_resolved(db):
    author = await _make_user(db, "report-svc-author-4")
    reporter = await _make_user(db, "report-svc-reporter-4")
    rating_id = await _make_review(db, "report-svc-movie-4", author)

    report, _ = await service.report_review(
        db, rating_id=rating_id, reason=None, reporter_id=reporter
    )

    resolved = await service.resolve_report(db, report_id=report.id)
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None


async def test_resolve_unknown_report_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        await service.resolve_report(db, report_id=888_888_888)
    assert exc.value.status_code == 404


# ── list_reports ─────────────────────────────────────────────────────────


async def test_list_reports_returns_paginated_shape(db):
    author = await _make_user(db, "report-svc-author-5")
    reporter = await _make_user(db, "report-svc-reporter-5")
    rating_id = await _make_review(db, "report-svc-movie-5", author)
    await service.report_review(db, rating_id=rating_id, reason="x", reporter_id=reporter)

    result = await service.list_reports(db, status="open", page=1, limit=20)
    assert result.page == 1
    assert result.limit == 20
    assert result.total >= 1
    assert all(item.status == "open" for item in result.items)
