import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from backlogg.admin.router import router as admin_router
from backlogg.books.routes import router as books_router
from backlogg.games.routes import router as games_router
from backlogg.genres.routes import router as genres_router
from backlogg.movies.routes import router as movies_router
from backlogg.people.routes import router as people_router
from backlogg.ratings.routes import ratings_router, user_reviews_router
from backlogg.search.routes import router as search_router
from backlogg.series.routes import router as series_router
from backlogg.trending.router import router as trending_router
from backlogg.users.routes import auth_router, users_router

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
