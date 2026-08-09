import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backlogg.admin.router import router as admin_router
from backlogg.books.routes import router as books_router
from backlogg.core.config import settings
from backlogg.core.http_cache import CacheHeadersMiddleware
from backlogg.core.metrics import MetricsMiddleware
from backlogg.core.observability import (
    RequestIDMiddleware,
    configure_logging,
    init_sentry,
    request_id_ctx,
)
from backlogg.feed.routes import feed_router
from backlogg.follows.routes import follows_router
from backlogg.games.routes import router as games_router
from backlogg.genres.routes import router as genres_router
from backlogg.library.routes import user_library_router
from backlogg.lists.routes import lists_router, user_lists_router
from backlogg.metrics.routes import router as metrics_router
from backlogg.movies.routes import router as movies_router
from backlogg.notifications.routes import notifications_router
from backlogg.people.routes import router as people_router
from backlogg.ratings.routes import ratings_router, user_reviews_router
from backlogg.recommendations.routes import recommendations_router
from backlogg.reports.routes import admin_reports_router, reports_router
from backlogg.search.routes import router as search_router
from backlogg.series.routes import router as series_router
from backlogg.trending.router import router as trending_router
from backlogg.users.routes import auth_router, users_router

# Structured JSON logging + optional Sentry, wired before the app handles any
# request. init_sentry is a no-op (and never imports sentry_sdk) without a DSN.
configure_logging(settings.LOG_LEVEL)
init_sentry()

_logger = logging.getLogger("backlogg.main")

API_DESCRIPTION = """\
Backlogg is a unified catalog API for **movies, series, books and games**,
seeded from public external APIs (TMDB, Open Library, IGDB) via a nightly sync,
plus a social layer on top of that catalog.

**Catalog & discovery:** list and detail endpoints per content type, cross-type
`/search` (with on-demand external fallback), `/genres`, `/trending`, `/people`
and similar-item recommendations.

**Social layer:** account management with refresh tokens and account recovery
(`/auth`, `/users`), ratings & reviews, per-user library/backlog, curated
`/lists`, `/follows`, an activity `/feed`, `/notifications` and personalized
`/recommendations`.

**Platform:** rate limiting, structured observability, Prometheus `/metrics`
and response caching.

## Authentication

- **User endpoints** use `Authorization: Bearer <access_token>`. Obtain the
  token pair from `POST /auth/login`; renew it with `POST /auth/refresh`.
- **Admin endpoints** (`/admin/*`) require the `X-API-Key` header.

Everything else is public. Direct messaging between users is out of scope.
"""

OPENAPI_TAGS = [
    {
        "name": "movies",
        "description": "Movie catalog: list, detail (on-demand fallback) and similar titles.",
    },
    {
        "name": "series",
        "description": "TV series catalog: list, detail (on-demand fallback) and similar titles.",
    },
    {
        "name": "books",
        "description": "Book catalog: list and detail, with on-demand fallback from Open Library.",
    },
    {
        "name": "games",
        "description": "Game catalog: list and detail, with on-demand fallback from IGDB.",
    },
    {
        "name": "people",
        "description": "People (cast & crew) with their credits across the catalog.",
    },
    {
        "name": "search",
        "description": "Cross-type full-text search with a rate-limited external fallback.",
    },
    {
        "name": "admin",
        "description": "Internal ops (sync trigger, stats). Requires the `X-API-Key` header.",
    },
    {
        "name": "genres",
        "description": "Genres per content type with live item counts.",
    },
    {
        "name": "trending",
        "description": "Trending movies and series from the TMDB Trending API.",
    },
    {
        "name": "auth",
        "description": "Registration, login, token refresh/logout and account recovery.",
    },
    {
        "name": "users",
        "description": "User profiles: own profile (`/users/me`) and public profiles by username.",
    },
    {
        "name": "ratings",
        "description": "Ratings & reviews across all types, review likes and per-user listings.",
    },
    {
        "name": "follows",
        "description": "Unidirectional follow relationships and follower/following listings.",
    },
    {
        "name": "feed",
        "description": "Personalized activity feed (following) and a popular reviews tab.",
    },
    {
        "name": "library",
        "description": "Per-user backlog: want / in_progress / completed / dropped, cross-type.",
    },
    {
        "name": "lists",
        "description": "Curated cross-type lists with ordering and public/private visibility.",
    },
    {
        "name": "notifications",
        "description": "Social notifications (new follower, review like) for the caller.",
    },
    {
        "name": "recommendations",
        "description": "On-the-fly recommendations from the caller's ratings and library.",
    },
    {
        "name": "reports",
        "description": "User-filed reports flagging reviews as problematic for admin moderation.",
    },
    {
        "name": "metrics",
        "description": "Prometheus metrics in the text exposition format. No authentication.",
    },
]

app = FastAPI(
    title="Backlogg API",
    version="0.1.0",
    description=API_DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


# Added before SecurityHeadersMiddleware so it is the innermost app middleware:
# it runs closest to the route (reads the final body to build the ETag / 304),
# and the security headers still decorate whatever response it returns.
app.add_middleware(CacheHeadersMiddleware)

app.add_middleware(SecurityHeadersMiddleware)

_cors_origins_env = os.getenv("CORS_ORIGINS", "")
if _cors_origins_env:
    _origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
else:
    _origins = ["http://localhost:3000", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Records request count + latency per (method, route template, status). Added
# just before RequestIDMiddleware so the latter stays the outermost middleware
# (request id set first) while metrics still wrap CORS/security headers/routing.
app.add_middleware(MetricsMiddleware)

# Registered last so it is the outermost user middleware: the request id is set
# before any other middleware or route runs and is available to every log line.
app.add_middleware(RequestIDMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log any uncaught exception correlated with the request id, return a 500.

    The response body is deliberately generic — internal details never leak to
    the client. The stack trace goes to the structured logs only.
    """
    _logger.exception(
        "request.unhandled_exception",
        extra={"method": request.method, "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={"X-Request-ID": request_id_ctx.get() or ""},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(movies_router)
app.include_router(series_router)
app.include_router(books_router)
app.include_router(games_router)
app.include_router(people_router)
app.include_router(search_router)
app.include_router(admin_router)
app.include_router(genres_router)
app.include_router(trending_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(ratings_router)
app.include_router(user_reviews_router)
app.include_router(follows_router)
app.include_router(feed_router)
app.include_router(user_library_router)
app.include_router(lists_router)
app.include_router(user_lists_router)
app.include_router(notifications_router)
app.include_router(recommendations_router)
app.include_router(reports_router)
app.include_router(admin_reports_router)
app.include_router(metrics_router)
