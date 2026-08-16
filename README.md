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

Requiere `uv` y Docker (no hace falta PostgreSQL nativo).

```bash
# 1. Dependencias
uv sync

# 2. Configuración — la plantilla ya trae la config de la DB local lista.
#    Solo rellena las credenciales de APIs externas si vas a usar
#    sync/on-demand en local (ver docs/external-apis.md).
cp .env.example .env

# 3. Base de datos local: Postgres en Docker, con datos persistentes.
#    Crea las DBs `backlogg` (dev) y `backlogg_test` (tests) en el primer
#    arranque. Ver docker-compose.yml.
docker compose up -d

# 4. Migraciones a la DB de dev (backlogg_test se automigra al correr los
#    tests, vía la fixture de tests/conftest.py)
uv run alembic upgrade head

# 5. Verificar el entorno completo: archivos, lint, formato y tests
bash init.sh

# Arrancar la API en local
uv run uvicorn backlogg.main:app --reload
```

Uso diario:

```bash
docker compose up -d          # levantar la DB (persiste entre reinicios)
docker compose down           # parar la DB conservando los datos
docker compose down -v        # parar y BORRAR los datos (empezar limpio)

uv run pytest -q              # solo tests
uv run ruff check .           # solo lint
docker compose exec db psql -U postgres -d backlogg   # inspección manual
```

> `DATABASE_URL` (DB de dev) y `TEST_DATABASE_URL` deben apuntar a DBs
> distintas — pytest trunca la de test en cada run. La plantilla ya las
> configura bien (`backlogg` vs `backlogg_test`).

### Dar acceso admin a un usuario (dev)

`is_admin` no tiene endpoint API (evita escalado de privilegios) — se activa
a mano en la DB. Si el `UPDATE` falla con `column "is_admin" does not exist`,
faltan migraciones por aplicar:

```bash
uv run alembic upgrade head
docker exec -it backlogg-db psql -U postgres -d backlogg \
  -c "UPDATE users SET is_admin = true WHERE username = '<username>';"
```

Cierra sesión y vuelve a iniciarla en el frontend para que `/v1/users/me`
refleje el cambio. Detalle completo en [`docs/schema.md`](docs/schema.md).

### Dar acceso superadmin a un usuario (dev)

`is_superadmin` sigue las mismas reglas que `is_admin`: tampoco tiene endpoint
API, se activa a mano en la DB por un operador. Es el único rol que puede
otorgar/revocar `is_admin` a **otros** usuarios, vía
`POST /v1/admin/users/{username}/grant-admin` y `/revoke-admin`.

```bash
uv run alembic upgrade head
docker exec -it backlogg-db psql -U postgres -d backlogg \
  -c "UPDATE users SET is_superadmin = true WHERE username = '<username>';"
```

En producción, el `UPDATE` equivalente se ejecuta directamente contra Neon
(consola SQL o `psql <connection-string>`) — no hay script ni endpoint para
esto, a propósito. Cierra sesión y vuelve a iniciarla para que
`/v1/users/me` refleje el cambio. Detalle completo (incluida la política de
auto-revocación) en [`docs/schema.md`](docs/schema.md).

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
