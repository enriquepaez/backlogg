from contextlib import asynccontextmanager

from fastapi import FastAPI

from backlogg.admin.router import router as admin_router
from backlogg.books.routes import router as books_router
from backlogg.games.routes import router as games_router
from backlogg.movies.routes import router as movies_router
from backlogg.people.routes import router as people_router
from backlogg.scheduler.setup import create_scheduler
from backlogg.search.routes import router as search_router
from backlogg.series.routes import router as series_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Backlogg API", lifespan=lifespan)


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
