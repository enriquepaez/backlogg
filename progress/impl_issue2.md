# impl_issue2 — Fix: on-demand movie fallback ignores year in slug

## Files modified

- `backlogg/movies/adapters/tmdb.py`
- `backlogg/movies/service.py`
- `tests/movies/test_service.py`

## What was implemented

### 1. `backlogg/movies/adapters/tmdb.py`

`search_movie` gained an optional `year: int | None = None` parameter.
When `year` is not None, `primary_release_year` is added to the TMDB query params.
TMDB uses this field to filter results to a specific release year, which prevents
returning a later film with the same title (e.g. Blade Runner 2049 instead of
Blade Runner 1982).

### 2. `backlogg/movies/service.py`

Added `_year_from_slug(slug: str) -> int | None` helper that extracts the trailing
4-digit year from a slug (e.g. `"blade-runner-1982"` -> `1982`), returning None if
absent.

In `get_movie`, the fallback path now calls `_year_from_slug(slug)` and passes the
result as `year=` to `_tmdb.search_movie(query, year=year)`.

### 3. `tests/movies/test_service.py`

Added `test_get_movie_fallback_passes_year_from_slug`: verifies that when
`get_movie` is called with slug `"blade-runner-1982"`, `search_movie` is invoked
with `("blade runner", year=1982)`.

## Test output

```
============================= test session starts ==============================
collected 17 items

tests/movies/test_repository.py::test_upsert_movie PASSED
tests/movies/test_repository.py::test_upsert_movie_idempotent PASSED
tests/movies/test_repository.py::test_get_movie_by_slug_not_found PASSED
tests/movies/test_repository.py::test_upsert_movie_multiple_genres PASSED
tests/movies/test_routes.py::test_get_movie_returns_200 PASSED
tests/movies/test_routes.py::test_get_movie_returns_404 PASSED
tests/movies/test_routes.py::test_get_movie_credits_empty PASSED
tests/movies/test_routes.py::test_get_movie_credits_present_and_ordered PASSED
tests/movies/test_service.py::test_get_movie_found_in_db PASSED
tests/movies/test_service.py::test_get_movie_fallback_to_tmdb PASSED
tests/movies/test_service.py::test_get_movie_not_found_anywhere PASSED
tests/movies/test_service.py::test_get_movie_fallback_passes_year_from_slug PASSED
tests/movies/test_similar_service.py::test_get_similar_movies_404_for_unknown_slug PASSED
tests/movies/test_similar_service.py::test_get_similar_movies_empty_when_no_tmdb_id PASSED
tests/movies/test_similar_service.py::test_get_similar_movies_persists_and_returns PASSED
tests/movies/test_similar_service.py::test_get_similar_movies_uses_local_if_already_present PASSED
tests/movies/test_similar_service.py::test_get_similar_movies_limits_to_10 PASSED

17 passed in 35.48s
```

ruff check and ruff format both pass with no errors.
