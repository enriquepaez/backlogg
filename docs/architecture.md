# Arquitectura — Qué significa "hacer un buen trabajo"

> Este documento define el estándar de calidad de backlogg.
> Los agentes revisores evalúan el código contra este archivo.
> Si no está aquí, no es un requisito.

## Visión general

Backlogg es una API de catálogo unificado para películas, series, libros y
videojuegos. Los ítems se sincronizan desde APIs públicas y se exponen vía REST.
El catálogo vive en PostgreSQL y crece por tres vías: sync nocturno por tramos,
backfill masivo bajo demanda (ver "Flujo de datos") y fallback on-demand —
cuando una búsqueda no encuentra resultados locales, el servicio consulta la
API externa, persiste el ítem y lo devuelve en la misma petición.

## Stack

- **Python 3.12+** gestionado con `uv`
- **FastAPI** — API REST async
- **SQLAlchemy 2.0** (typed) + **Alembic** — ORM y migraciones
- **Pydantic v2** — validación de request/response
- **GitHub Actions** — sync nocturno (`.github/workflows/nightly-sync.yml`)
  que llama a los endpoints `/v1/admin/sync/{type}`; la instancia free de Render
  duerme sin tráfico, por lo que no puede haber schedulers embebidos en el proceso
- **PostgreSQL** (Neon en producción)
- **ruff** — linting y formato
- **pytest** — suite de tests
- **Render** — despliegue

## Estructura del proyecto

Vertical slices por dominio. Cada dominio contiene todo lo necesario:

```
backlogg/
├── <domain>/              # movies, series, books, games, people, search,
│   │                      # genres, trending, users, ratings, follows, feed,
│   │                      # library, notifications, recommendations
│   ├── models.py          # SQLAlchemy ORM models
│   ├── schemas.py         # Pydantic v2 request/response schemas
│   ├── repository.py      # DB queries (solo este archivo toca SQLAlchemy)
│   ├── service.py         # Lógica de negocio + on-demand fallback
│   ├── routes.py          # FastAPI router (sin lógica, solo delega)
│   └── adapters/          # Clientes de APIs externas
├── admin/                 # POST /v1/admin/sync/{type}, GET /v1/admin/stats
│   └── auth.py            # X-API-Key dependency para /v1/admin/*
├── scheduler/
│   ├── jobs.py            # sync_movies/series/books/games (por tramos)
│   └── repository.py      # Cursores de sync (tabla sync_cursors)
├── shared/
│   ├── models.py          # Person, Credit (transversales a todos los dominios)
│   ├── bulk_load.py       # Ruta de escritura por lotes (COPY + upserts) para
│   │                      # ingesta masiva; el descriptor por tipo vive en
│   │                      # cada <domain>/repository.py
│   └── external_ids.py    # Utilidades polimórficas de external_ids
└── core/
    ├── database.py        # Engine, SessionLocal, get_db dependency
    └── config.py          # Settings via pydantic-settings

scripts/
├── backfill_sync.py       # Backfill directo contra la DB (ver docs/operations.md)
└── bench_bulk_load.py     # Benchmark ruta por ítem vs. ruta por lotes
```

## Principios

1. **Vertical slices, no capas horizontales.** Cada dominio es autocontenido.
   No crear `services/` global ni `repositories/` global.

2. **Sin lógica en las rutas.** Los routers solo validan entrada, llaman al
   servicio y devuelven la respuesta. Toda la lógica va en `service.py`.

3. **Repositorios como frontera de persistencia.** Solo `repository.py`
   importa y usa SQLAlchemy. `service.py` no escribe queries.

4. **On-demand fallback en el servicio.** Patrón estándar para `GET /{slug}`:
   1. Consultar repositorio local.
   2. Si no hay resultado → llamar al adaptador externo.
   3. Persistir y devolver el resultado.
   4. Si tampoco hay resultado externo → `404`.

5. **Errores explícitos.** Las rutas lanzan `HTTPException`. Los servicios
   lanzan excepciones de dominio. Nunca retornar `None` donde se esperaba un objeto.

6. **Atomicidad en migraciones.** Cada feature tiene su propia migración Alembic.
   Una migración nunca recrea tablas ya creadas en migraciones anteriores.
   El implementer debe leer TODOS los archivos de migración existentes antes de
   escribir uno nuevo.

7. **Scope.** Catálogo, auth (con refresh tokens y recuperación de cuenta),
   ratings/reviews propios (`rating_internal`, agregado desde `user_ratings`),
   biblioteca/backlog por usuario, recomendaciones personalizadas y capa
   social (follows + feed + notificaciones). Como capa de plataforma: rate
   limiting, observabilidad, métricas y caché. Mensajería directa entre
   usuarios está **fuera de scope**.

## Flujo de datos

```
cliente HTTP
    │
    ▼
routes.py  ──── Pydantic v2 (validación entrada/salida)
    │
    ▼
service.py ──── on-demand fallback
    ├──────────────────────────────► adapters/ (TMDB / Open Library / IGDB)
    │
    ▼
repository.py ── SQLAlchemy 2.0 typed queries
    │
    ▼
PostgreSQL
```

El catálogo se puebla por dos caminos además del fallback on-demand:

- **Nightly** (GitHub Actions → `POST /v1/admin/sync/{type}`): cada noche avanza
  un tramo de `SYNC_SLICE_SIZE` items por tipo, con cursor persistido en
  `sync_cursors`.
- **Backfill** (GitHub Actions → `scripts/backfill_sync.py`): reutiliza los
  mismos jobs de `scheduler/jobs.py` pero escribe directo contra la DB en
  bucle, para poblar el catálogo completo en horas en lugar de meses.
  Comandos y procedimiento en `docs/operations.md`.

## APIs externas

| Tipo de contenido | Fuente       | Auth                      |
|-------------------|--------------|---------------------------|
| Películas/Series  | TMDB         | API key                   |
| Libros            | Open Library | Sin auth                  |
| Juegos            | IGDB         | Twitch client credentials |

Ver `docs/external-apis.md` para endpoints y variables de entorno requeridas.

## Qué NO hacer

- ❌ Lógica de negocio en `routes.py`.
- ❌ Queries SQL directas en `service.py`.
- ❌ Devolver modelos SQLAlchemy directamente — siempre serializar con Pydantic.
- ❌ IDs numéricos en URLs — usar slugs siempre.
- ❌ Asumir que SQLAlchemy convierte strings a `date`/`datetime` — hacerlo explícito.
- ❌ Features fuera del MVP scope.
