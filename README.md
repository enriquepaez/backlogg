# Backlogg

API de catálogo unificado para películas, series, libros y videojuegos.
Items sincronizados desde APIs públicas y expuestos vía REST. El catálogo
vive en PostgreSQL y crece por tres vías: sync nocturno por tramos, backfill
masivo bajo demanda y fallback on-demand — cuando una búsqueda no encuentra
resultados locales, el servicio consulta la API externa, persiste el ítem y
lo devuelve en la misma petición.

## Stack

- **Python 3.12+** gestionado con `uv`
- **FastAPI** — API REST async
- **SQLAlchemy 2.0** + **Alembic** — ORM y migraciones
- **Pydantic v2** — validación request/response
- **PostgreSQL** (Neon en producción)
- **Render** — despliegue (free tier; la instancia duerme sin tráfico)
- **GitHub Actions** — CI, sync nocturno y backfill (no hay schedulers
  embebidos en el proceso)
- **ruff** — linting y formato
- **pytest** — suite de tests

## Quickstart

```bash
# Dependencias (requiere uv y un PostgreSQL local)
uv sync

# Configuración — rellenar credenciales (ver docs/external-apis.md)
cp .env.example .env

# Verificar el entorno completo: archivos, lint, formato y suite de tests
bash init.sh

# Arrancar la API en local (aplica migraciones vía entrypoint en deploy;
# en local: uv run alembic upgrade head)
uv run uvicorn backlogg.main:app --reload

# Solo tests / solo lint
uv run pytest -q
uv run ruff check .
```

## API

| Endpoint | Descripción |
|---|---|
| `GET /health` | Health check |
| `GET /search?q=` | Búsqueda cross-type con fallback a APIs externas |
| `GET /{tipo}` | Listados paginados con filtro por género y ordenación |
| `GET /{tipo}/{slug}` | Detalle con `credits[]` y fallback on-demand |
| `GET /movies\|series/{slug}/similar` | Similares vía TMDB |
| `GET /genres?type=` | Géneros con conteo de items |
| `GET /trending?type=&period=` | Trending de movies/series vía TMDB |
| `POST /admin/sync/{tipo}` | Sync manual por tramos (requiere `X-API-Key`) |
| `GET /admin/stats` | Counts y último sync por tipo (requiere `X-API-Key`) |

`{tipo}` ∈ `movies`, `series`, `books`, `games`. Contratos completos en
[`docs/api.md`](docs/api.md).

## APIs externas

| Tipo          | Fuente       | Auth                    |
|---------------|--------------|-------------------------|
| Películas/Series | TMDB      | API key                 |
| Libros        | Open Library | Sin auth                |
| Juegos        | IGDB         | Twitch client credentials |

## Documentación

- [`docs/architecture.md`](docs/architecture.md) — estructura y principios
- [`docs/api.md`](docs/api.md) — contratos de los endpoints
- [`docs/operations.md`](docs/operations.md) — runbook: nightly sync, backfill, admin, secrets
- [`docs/schema.md`](docs/schema.md) — esquema de la base de datos
- [`docs/external-apis.md`](docs/external-apis.md) — referencia APIs externas
- [`docs/conventions.md`](docs/conventions.md) — reglas de código
- [`docs/verification.md`](docs/verification.md) — cómo verificar el trabajo

## Harness Engineering

Este proyecto usa un sistema leader/implementer/reviewer. Ver `AGENTS.md`
para el mapa completo de cómo trabajan los agentes de IA en este repo.

```bash
# Verificar estado del entorno
bash init.sh
```
