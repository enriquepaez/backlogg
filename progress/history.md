# Historial de sesiones

<!-- Append-only. Añadir una línea al cerrar cada feature. -->
<!-- Formato: YYYY-MM-DD | feat_<id> <name> | resumen de una línea -->
2026-05-24 | feat_1 shared_models | pyproject.toml + core (config, database) + shared/models.py (Person, Credit) + shared/external_ids.py (ExternalId, helpers upsert/get/set) + migración Alembic 0001 (external_ids, people, credits con triggers) + 5 tests en verde.
2026-05-24 | feat_2 movies | movies/models.py (Movie, MovieGenre, join) + movies/schemas.py (MovieOut, GenreOut) + movies/repository.py (get_by_slug, upsert con get-or-create genres) + movies/adapters/tmdb.py (TMDBClient: search + detail + slugify) + movies/service.py (on-demand fallback) + movies/routes.py (GET /movies/{slug}) + main.py (FastAPI app + /health) + migración Alembic 0002 + 14 tests en verde (4 repo + 3 servicio + 2 rutas + 5 heredados).
