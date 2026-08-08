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
from backlogg.search.routes import router as search_router
from backlogg.series.routes import router as series_router
from backlogg.trending.router import router as trending_router
from backlogg.users.routes import auth_router, users_router

# Structured JSON logging + optional Sentry, wired before the app handles any
# request. init_sentry is a no-op (and never imports sentry_sdk) without a DSN.
configure_logging(settings.LOG_LEVEL)
init_sentry()

_logger = logging.getLogger("backlogg.main")

app = FastAPI(title="Backlogg API")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


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
app.include_router(metrics_router)
