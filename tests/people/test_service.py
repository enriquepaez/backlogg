"""Tests for backlogg/people/service.py — repository is mocked."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backlogg.people import service
from backlogg.people.schemas import PersonOut


def _make_person_out(slug: str = "keanu-reeves") -> PersonOut:
    return PersonOut(
        id=1,
        name="Keanu Reeves",
        slug=slug,
        profile_url="https://example.com/keanu.jpg",
        credits=[],
    )


async def test_get_person_found(db):
    """When person exists in DB, service returns PersonOut."""
    person_out = _make_person_out()
    with patch(
        "backlogg.people.service.repo.get_person_by_slug",
        new_callable=AsyncMock,
        return_value=person_out,
    ):
        result = await service.get_person(db, "keanu-reeves")

    assert result.slug == "keanu-reeves"
    assert result.name == "Keanu Reeves"


async def test_get_person_not_found(db):
    """When person does not exist in DB, service raises HTTP 404."""
    with patch(
        "backlogg.people.service.repo.get_person_by_slug",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await service.get_person(db, "nobody-here-999")

    assert exc_info.value.status_code == 404
