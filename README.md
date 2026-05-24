# Backlogg

API de catálogo unificado para películas, series, libros y videojuegos.
Items sincronizados desde APIs públicas y expuestos vía REST. El catálogo
vive en PostgreSQL local y crece bajo demanda — cuando una búsqueda no
encuentra resultados locales, el servicio consulta la API externa, persiste
el ítem y lo devuelve en la misma petición.

## Stack

- **Python 3.12+** gestionado con `uv`
- **FastAPI** — API REST async
- **SQLAlchemy 2.0** + **Alembic** — ORM y migraciones
- **Pydantic v2** — validación request/response
- **APScheduler** — sync jobs nocturnos embebidos en FastAPI
- **PostgreSQL** (Neon en producción)
- **ruff** — linting y formato
- **pytest** — suite de tests
- **Fly.io** — despliegue

## APIs externas

| Tipo          | Fuente       | Auth                    |
|---------------|--------------|-------------------------|
| Películas/Series | TMDB      | API key                 |
| Libros        | Open Library | Sin auth                |
| Juegos        | IGDB         | Twitch client credentials |

## Documentación

- [`docs/architecture.md`](docs/architecture.md) — estructura y principios
- [`docs/conventions.md`](docs/conventions.md) — reglas de código
- [`docs/verification.md`](docs/verification.md) — cómo verificar el trabajo
- [`docs/schema.md`](docs/schema.md) — esquema de la base de datos
- [`docs/api.md`](docs/api.md) — contratos de los endpoints
- [`docs/external-apis.md`](docs/external-apis.md) — referencia APIs externas

## Harness Engineering

Este proyecto usa un sistema leader/implementer/reviewer. Ver `AGENTS.md`
para el mapa completo de cómo trabajan los agentes de IA en este repo.

```bash
# Verificar estado del entorno
bash init.sh
```
