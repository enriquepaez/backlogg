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

## Colección Bruno (obligatoria)

- **Todo endpoint expuesto por la API debe tener al menos una request en la
  colección `bruno/`.** Un endpoint nuevo sin su `.bru` correspondiente es
  motivo de rechazo.
- Al añadir o modificar endpoints en una feature, actualiza `bruno/` en el
  mismo cambio: crea el `.bru` del happy path y, cuando aporte valor, los casos
  de error relevantes (401/403/404/422).
- Organización: una carpeta por dominio (`bruno/<Dominio>/`), un `.bru` por
  request. Sigue el formato existente: `meta` con `name`/`seq`, bloque de
  método con `url: {{baseUrl}}/...`, `auth: bearer` con `token: {{authToken}}`
  para endpoints autenticados, y un bloque `tests` que al menos verifique el
  status code esperado.
- Las variables compartidas (`baseUrl`, `authToken`, `refreshToken`,
  `adminApiKey`) viven en `bruno/environments/local.bru`; no hardcodees hosts
  ni tokens en las requests.

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
- **`downgrade()` no-op**: permitido **solo** cuando la migración borra datos
  **derivados** y regenerables por reingesta, nunca cuando toca esquema ni datos
  de usuario. Una purga de ese tipo no tiene inversa —no hay copia que
  restaurar— y lanzar una excepción solo bloquearía un downgrade legítimo del
  esquema circundante. En ese caso el cuerpo lleva un comentario que explique
  por qué es un no-op y cómo se repuebla el dato. Precedente: `0033`
  (purga de `book_genres`, repoblada por `scripts/backfill_sync.py book`).

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
  por test **dentro de cada `item_type`** para evitar violaciones de
  `uq_external_id` (`item_type`, `source`, `external_id`) cuando los tests
  comparten la misma DB. Un mismo id en dos tipos distintos ya no colisiona
  — desde la migración `0036`, issue #20.

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
