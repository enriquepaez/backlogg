from fastapi import FastAPI

from backlogg.books.routes import router as books_router
from backlogg.games.routes import router as games_router
from backlogg.movies.routes import router as movies_router
from backlogg.people.routes import router as people_router
from backlogg.search.routes import router as search_router
from backlogg.series.routes import router as series_router

app = FastAPI(title="Backlogg API")


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(movies_router)
app.include_router(series_router)
app.include_router(books_router)
app.include_router(games_router)
app.include_router(people_router)
app.include_router(search_router)
