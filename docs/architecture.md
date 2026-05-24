# Arquitectura — Qué significa "hacer un buen trabajo"

> Este documento define el estándar de calidad de backlogg.
> Los agentes revisores evalúan el código contra este archivo.
> Si no está aquí, no es un requisito.

## Visión general

Backlogg es una API de catálogo unificado para películas, series, libros y
videojuegos. Los ítems se sincronizan desde APIs públicas y se exponen vía REST.
El catálogo vive en PostgreSQL local y crece bajo demanda — cuando una búsqueda
no encuentra resultados locales, el servicio consulta la API externa, persiste
el ítem y lo devuelve en la misma petición.

## Stack

- **Python 3.12+** gestionado con `uv`
- **FastAPI** — API REST async
- **SQLAlchemy 2.0** (typed) + **Alembic** — ORM y migraciones
- **Pydantic v2** — validación de request/response
- **APScheduler** — sync jobs nocturnos, embebidos en el proceso FastAPI
- **PostgreSQL** (Neon en producción)
- **ruff** — linting y formato
- **pytest** — suite de tests
- **Fly.io** — despliegue

## Estructura del proyecto

Vertical slices por dominio. Cada dominio contiene todo lo necesario:

```
backlogg/
├── <domain>/              # movies, series, books, games, people, search
│   ├── models.py          # SQLAlchemy ORM models
│   ├── schemas.py         # Pydantic v2 request/response schemas
│   ├── repository.py      # DB queries (solo este archivo toca SQLAlchemy)
│   ├── service.py         # Lógica de negocio + on-demand fallback
│   ├── routes.py          # FastAPI router (sin lógica, solo delega)
│   └── adapters/          # Clientes de APIs externas
├── shared/
│   ├── models.py          # Person, Credit (transversales a todos los dominios)
│   └── external_ids.py    # Utilidades polimórficas de external_ids
└── core/
    ├── database.py        # Engine, SessionLocal, get_db dependency
    └── config.py          # Settings via pydantic-settings
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

7. **MVP scope.** Auth, listas de usuario, ratings propios, reviews y features
   sociales están **fuera de scope**. `rating_internal` es siempre 0/NULL.

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
