# Conventions — Reglas de código obligatorias

> El agente reviewer verifica cada una de estas reglas. Una violación es
> motivo de rechazo inmediato.

## Identificadores y URLs

- **Slugs** como identificadores en URLs, nunca IDs numéricos de DB.
  - ✅ `GET /movies/the-matrix-1999`
  - ❌ `GET /movies/42`
- Los slugs se generan al persistir el ítem y no cambian.

## FastAPI

- **Async route handlers** con `Depends` injection para la sesión de DB.
  ```python
  @router.get("/{slug}", response_model=MovieOut)
  async def get_movie(slug: str, db: AsyncSession = Depends(get_db)):
      ...
  ```
- **Pydantic v2 models** como `response_model`. Nunca devolver dicts crudos.
- Un `APIRouter` por dominio, montado en `backlogg/main.py`.

## SQLAlchemy 2.0

- **Typed queries** con `select()`, `scalars()`, `scalar_one_or_none()`.
  ```python
  result = await db.execute(select(Movie).where(Movie.slug == slug))
  return result.scalar_one_or_none()
  ```
- Usar `AsyncSession` — nunca `Session` síncrona en código de producción.
- No usar `db.query()` (API legacy de 1.x).

## Fechas y horas

- Los campos de fecha de APIs externas **siempre** se convierten explícitamente
  a objetos Python antes de pasarlos al repositorio:
  ```python
  # ✅ Correcto
  release_date = date.fromisoformat(raw["release_date"])
  # ❌ Incorrecto — no asumir que SQLAlchemy coerce strings
  release_date = raw["release_date"]
  ```

## Migraciones Alembic

- Una migración por feature. El nombre sigue el patrón:
  `<revision>_<feature_name>.py`
- El implementer **debe leer todos los archivos de migración existentes** antes
  de escribir uno nuevo para no recrear tablas ya creadas.
- Cada migración incluye `upgrade()` y `downgrade()`.

## External IDs

- Usar el patrón polimórfico de `backlogg/shared/external_ids.py`.
- `external_ids` y `credits`: no tienen FK reales — la integridad es
  responsabilidad del código de aplicación.

## Tests

- **Tests de repositorio:** PostgreSQL real, sin mocks.
- **Tests de servicio:** mock del adaptador externo.
- **Tests de endpoint:** `TestClient` de FastAPI / `httpx.AsyncClient`.
- Cada nuevo endpoint tiene **al menos un test** (happy path).
- Los datos de test que usan `external_ids` deben tener IDs externos únicos
  por test para evitar violaciones de `uq_external_id` cuando los tests
  comparten la misma DB.

## Linting y formato

- Todo el código pasa `uv run ruff check .` sin errores.
- Todo el código pasa `uv run ruff format --check .` sin errores.
- El formatter se aplica antes de declarar la feature como hecha.

## Nombrado de ramas

Las ramas siguen el patrón `<tipo>/<descripcion-en-kebab-case>`.

| Prefijo   | Cuándo usarlo                                              | Ejemplo                          |
|-----------|------------------------------------------------------------|----------------------------------|
| `feat/`   | Nueva funcionalidad o endpoint                             | `feat/search-books`              |
| `fix/`    | Corrección de bug (código de producción o tests)           | `fix/credits-mock-missing`       |
| `chore/`  | Tareas de mantenimiento: deps, CI, config, docs            | `chore/update-ruff`              |
| `refactor/` | Reestructuración sin cambio de comportamiento observable | `refactor/service-layer-cleanup` |
| `docs/`   | Cambios exclusivos en documentación                        | `docs/add-branch-conventions`    |

Reglas:
- ❌ **Nunca** usar `feat/` para bugfixes, aunque el fix sea pequeño.
- ❌ **Nunca** trabajar directamente en `main`.
- El prefijo debe coincidir con el del commit message (`feat:`, `fix:`, etc.).

## Nombrado de archivos de progreso

| Archivo                        | Quién lo escribe  | Contenido                          |
|--------------------------------|-------------------|------------------------------------|
| `progress/current.md`          | Leader / Implementer | Plan y estado de la sesión actual |
| `progress/impl_<feature_id>.md` | Implementer      | Informe de implementación          |
| `progress/review_<feature_id>.md` | Reviewer       | Veredicto de revisión              |
| `progress/history.md`          | Leader           | Bitácora append-only               |
