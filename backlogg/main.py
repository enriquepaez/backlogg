from fastapi import FastAPI

from backlogg.movies.routes import router as movies_router
from backlogg.series.routes import router as series_router

app = FastAPI(title="Backlogg API")


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(movies_router)
app.include_router(series_router)
