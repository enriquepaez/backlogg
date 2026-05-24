# CHECKPOINTS — Criterios objetivos de "estado final correcto"

> El reviewer marca `[x]` los que se cumplen y `[ ]` los que no.
> No se puede aprobar una feature con ningún checkpoint en `[ ]`.

## Siempre obligatorios (todas las features)

- [ ] **C1** — `bash init.sh` termina sin errores (código de salida 0).
- [ ] **C2** — No hay `print()` de debug en el código nuevo.
- [ ] **C3** — No hay TODOs sin contexto en el código nuevo.
- [ ] **C4** — `ruff check` y `ruff format --check` pasan sin errores.
- [ ] **C5** — Todos los tests pasan (`uv run pytest`).

## Modelos y migraciones

- [ ] **C6** — El modelo SQLAlchemy usa SQLAlchemy 2.0 (no legacy 1.x).
- [ ] **C7** — La migración Alembic no recrea tablas ya creadas en migraciones anteriores.
- [ ] **C8** — La migración incluye `upgrade()` y `downgrade()` implementados.

## Endpoints

- [ ] **C9** — Los route handlers son `async` y usan `Depends(get_db)`.
- [ ] **C10** — El `response_model` es un schema Pydantic v2 (no dict).
- [ ] **C11** — Los URLs usan slugs, no IDs numéricos.
- [ ] **C12** — El endpoint devuelve `404` si el slug no existe ni en DB ni en API externa.
- [ ] **C13** — Cada nuevo endpoint tiene al menos un test de happy path.

## Fechas y datos externos

- [ ] **C14** — Los campos de fecha de APIs externas se convierten explícitamente
  a `date`/`datetime` antes de pasarlos al repositorio.
- [ ] **C15** — Los datos de test con `external_ids` usan IDs únicos por test.

## On-demand fallback (si aplica)

- [ ] **C16** — El fallback persiste el ítem en DB antes de devolverlo.
- [ ] **C17** — Si la API externa tampoco encuentra el ítem, devuelve `404`.

## Scheduler (solo feat 8)

- [ ] **C18** — El sync es idempotente (re-ejecutar no crea duplicados).
- [ ] **C19** — Un error en un job no aborta los demás jobs.

## Separación de capas

- [ ] **C20** — No hay lógica de negocio en `routes.py`.
- [ ] **C21** — No hay queries SQLAlchemy en `service.py`.
- [ ] **C22** — No se devuelven modelos ORM directamente — siempre Pydantic.
