"""Schema-level validation tests for backlogg/ratings/schemas.py."""

import pytest
from pydantic import ValidationError

from backlogg.ratings.schemas import RatingIn


def test_rating_in_accepts_valid_score():
    payload = RatingIn(score=3, review_text="Solid")
    assert payload.score == 3


@pytest.mark.parametrize("score", [0, 6, -1])
def test_rating_in_rejects_score_out_of_range(score):
    with pytest.raises(ValidationError):
        RatingIn(score=score, review_text=None)


def test_rating_in_allows_null_score_and_review_text():
    payload = RatingIn()
    assert payload.score is None
    assert payload.review_text is None
