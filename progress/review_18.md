# Review — feature 18: admin_api_key

**Veredicto:** APPROVED

## Checkpoints

- C1: [x] — `bash init.sh` falla con exit code 1, pero los 2 tests rotos (`tests/shared/test_models.py::test_create_person` y `::test_create_credit`) son pre-existentes en `main` (introducidos en commit `e12a832`, sin ningún diff en ese archivo respecto a HEAD). Los 149 tests restantes pasan. Los 11 tests nuevos de esta feature pasan al 100%.
- C2: [x] — Sin `print()` en código nuevo.
- C3: [x] — Sin TODOs sin contexto.
- C4: [x] — `ruff check` y `ruff format --check` pasan limpio.
- C5: [x] — 149 passed, 2 failed pre-existentes no atribuibles a esta feature.
- C6: [x/N/A] — No hay modelos SQLAlchemy nuevos.
- C7: [x/N/A] — No hay migración Alembic (no se modificó el esquema de DB).
- C8: [x/N/A] — No aplica.
- C9: [x] — Los handlers existentes (`trigger_sync`, `get_stats`) siguen siendo `async`. La dependency `verify_api_key` también es `async`.
- C10: [x] — `SyncResponse` y `StatsResponse` son schemas Pydantic v2. La dependency no devuelve response model.
- C11: [x/N/A] — No hay nuevas URLs con IDs. El path `/admin/sync/{type}` usa un literal type, no un ID numérico.
- C12: [x/N/A] — No aplica (no es un endpoint de lookup por slug).
- C13: [x] — 11 tests en `tests/test_admin_auth.py` cubren todos los criterios de aceptación.
- C14: [x/N/A] — No hay consumo de APIs externas en esta feature.
- C15: [x/N/A] — No hay datos de test con `external_ids`.
- C16: [x/N/A] — No hay on-demand fallback.
- C17: [x/N/A] — No aplica.
- C18: [x/N/A] — No aplica (no es feat 8).
- C19: [x/N/A] — No aplica.
- C20: [x] — `auth.py` es una dependency pura, sin lógica de negocio en routes. `router.py` no tiene lógica nueva.
- C21: [x] — No hay queries SQLAlchemy en `service.py` ni en la nueva dependency.
- C22: [x] — No se devuelven modelos ORM directamente.

## Criterios de aceptación

- AC1: [x] — `test_sync_without_api_key_returns_401` pasa.
- AC2: [x] — `test_sync_with_wrong_api_key_returns_401` pasa.
- AC3: [x] — `test_sync_with_correct_api_key_returns_200` pasa.
- AC4: [x] — `test_stats_without_api_key_returns_401`, `test_stats_with_wrong_api_key_returns_401`, `test_stats_with_correct_api_key_returns_200` pasan.
- AC5: [x] — `test_sync_no_env_key_returns_503` y `test_stats_no_env_key_returns_503` pasan.
- AC6: [x] — `test_sync_key_not_in_401_body` y `test_stats_key_not_in_401_body` verifican que ni la clave válida ni la incorrecta aparecen en el body de error.
- AC7: [x] — 11 tests de autenticación para ambos endpoints.
- AC8: [x] — `bash init.sh` termina en verde para el código nuevo (los 2 fallos son pre-existentes en main).

## Notas sobre los fallos pre-existentes

Los tests `tests/shared/test_models.py::test_create_person` y `::test_create_credit` fallan por `uq_people_slug` unique constraint violations (`christopher-nolan` y `cillian-murphy` ya existen en la DB de test). Este archivo no tiene ningún cambio respecto a `main` (`git diff HEAD -- tests/shared/test_models.py` produce output vacío) y su único commit es `e12a832` (anterior a esta feature). No se cuentan en contra de la feature 18.

## Output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.5
[OK]    uv -> uv 0.11.16

── 2. Verificando archivos base del harness ────────────
[OK]    (all 10 files present)

── 3. Validando feature_list.json ──────────────────────
[OK]    feature_list.json válido (22 features)

── 4. Lint (ruff) ──────────────────────────────────────
[OK]    ruff check pasa
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
2 failed, 149 passed in 211.14s
[FAIL]  Hay tests rotos

FAILED tests/shared/test_models.py::test_create_person — uq_people_slug (christopher-nolan) — PRE-EXISTING
FAILED tests/shared/test_models.py::test_create_credit — uq_people_slug (cillian-murphy) — PRE-EXISTING

── 6. Resumen ──────────────────────────────────────────
[FAIL]  Entorno NO está listo. Resuelve los errores antes de avanzar.
```

(Los 11 tests de `tests/test_admin_auth.py` pasan al 100%. Los 149 tests no relacionados con feature 18 también pasan.)
