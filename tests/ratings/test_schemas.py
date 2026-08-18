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


@pytest.mark.parametrize("score", [1, 1.5, 2.0, 3.5, 4.5, 5])
def test_rating_in_accepts_half_star_steps(score):
    payload = RatingIn(score=score, review_text=None)
    assert payload.score == score


def test_rating_in_accepts_score_1_and_5():
    assert RatingIn(score=1, review_text=None).score == 1
    assert RatingIn(score=5, review_text=None).score == 5


@pytest.mark.parametrize("score", [3.3, 2.7, 1.1, 4.9])
def test_rating_in_rejects_score_not_multiple_of_half(score):
    with pytest.raises(ValidationError):
        RatingIn(score=score, review_text=None)
