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
# Dependencias (requiere uv; no requiere PostgreSQL nativo, ver Docker abajo)
uv sync

# Configuración — copiar plantilla y rellenar credenciales de APIs externas
# (ver docs/external-apis.md)
cp .env.example .env

# Sin PostgreSQL nativo: levantar uno vía Docker (una sola vez; crea las
# DBs backlogg y backlogg_test con auth trust, rol = usuario del SO)
docker run -d --name backlogg-test-pg -p 5432:5432 \
  -e POSTGRES_USER=$(whoami) -e POSTGRES_HOST_AUTH_METHOD=trust \
  -e POSTGRES_DB=backlogg_test postgres:16-alpine
psql -h localhost -U $(whoami) -d postgres -c 'CREATE DATABASE backlogg'

# En sesiones siguientes, si el contenedor existe pero está parado:
docker start backlogg-test-pg

# En .env: DATABASE_URL debe apuntar a `backlogg` (DB de dev) y
# TEST_DATABASE_URL a `backlogg_test` (DB de test, que pytest trunca en
# cada run) — NUNCA la misma DB en ambas, o pytest borra tus datos de dev.
# Con auth trust no hace falta contraseña:
#   DATABASE_URL=postgresql+asyncpg://<tu-usuario-unix>@localhost/backlogg
#   TEST_DATABASE_URL=postgresql+asyncpg://<tu-usuario-unix>@localhost/backlogg_test

# Aplicar migraciones a la DB de dev (backlogg_test se automigra al correr
# los tests, vía la fixture apply_migrations de tests/conftest.py)
uv run alembic upgrade head

# Verificar el entorno completo: archivos, lint, formato y suite de tests
bash init.sh

# Arrancar la API en local
uv run uvicorn backlogg.main:app --reload

# Conectarse a la DB de dev para inspección manual
psql -h localhost -U $(whoami) -d backlogg

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
