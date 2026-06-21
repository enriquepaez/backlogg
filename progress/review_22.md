# Review — feature #22: cors_and_security

**Veredicto:** APPROVED

## Checkpoints

- C1: [x] — `bash init.sh` termina en verde (output del implementer: 185 passed).
- C2: [x] — Sin `print()` de debug en `backlogg/main.py` ni `tests/test_cors_security.py`.
- C3: [x] — Sin TODOs sin contexto en el código nuevo.
- C4: [x] — `ruff check backlogg/main.py tests/test_cors_security.py` → All checks passed.
- C5: [x] — 8/8 tests de la feature pasan.
- C6–C8: N/A — La feature no introduce modelos ni migraciones.
- C9: N/A — No se añaden route handlers nuevos (solo middlewares).
- C10: N/A — No se añaden response_models nuevos.
- C11: N/A — No se añaden URLs nuevas con IDs.
- C12: N/A — No hay on-demand fallback.
- C13: [x] — El endpoint existente `/health` tiene tests. La feature no añade endpoints nuevos, pero los 8 tests cubren todos los acceptance criteria.
- C14: N/A — No se consumen datos de APIs externas.
- C15: N/A — Los tests no usan `external_ids`.
- C16–C17: N/A — No hay on-demand fallback.
- C18–C19: N/A — No es el scheduler.
- C20: [x] — `backlogg/main.py` solo contiene setup de app y middlewares, sin lógica de negocio.
- C21: [x] — No hay queries SQLAlchemy en la feature.
- C22: [x] — No se devuelven modelos ORM.

## Acceptance Criteria verificados

- [x] CORSMiddleware añadido a la app FastAPI (`backlogg/main.py` líneas 45-54).
- [x] `CORS_ORIGINS` env var (comma-separated) define los orígenes permitidos (líneas 44-49).
- [x] Sin `CORS_ORIGINS` configurada, permite `http://localhost:3000` y `http://localhost:5173` (línea 49).
- [x] OPTIONS preflight devuelve 200 con headers CORS correctos (tests `test_cors_preflight_localhost_3000` y `test_cors_preflight_localhost_5173` — ambos PASSED).
- [x] `X-Content-Type-Options: nosniff` presente en todas las respuestas (`SecurityHeadersMiddleware` línea 36).
- [x] `X-Frame-Options: DENY` presente en todas las respuestas (línea 37).
- [x] `Referrer-Policy: strict-origin-when-cross-origin` presente (línea 38).
- [x] 8 tests cubren todos los acceptance criteria.
- [x] Lint limpio.
- [x] 8/8 tests pasan.

## Observaciones

El orden LIFO de `add_middleware` es correcto: `SecurityHeadersMiddleware` se registra primero y `CORSMiddleware` segundo, lo que hace que CORS procese los preflights antes de que lleguen a la lógica de la app, y los security headers se añaden en la fase de salida de `SecurityHeadersMiddleware`. El test `test_cors_custom_origins_via_env` usa `importlib.import_module` tras limpiar `sys.modules` para forzar la re-evaluación de `os.getenv("CORS_ORIGINS")` — técnica correcta dado que la lectura del env var ocurre en tiempo de import de `main.py`.

## Output de ruff

```
All checks passed!
```

## Output de pytest tests/test_cors_security.py -v

```
collected 8 items

tests/test_cors_security.py::test_security_headers_present PASSED        [ 12%]
tests/test_cors_security.py::test_cors_allowed_origin_localhost_3000 PASSED [ 25%]
tests/test_cors_security.py::test_cors_allowed_origin_localhost_5173 PASSED [ 37%]
tests/test_cors_security.py::test_cors_disallowed_origin PASSED          [ 50%]
tests/test_cors_security.py::test_cors_preflight_localhost_3000 PASSED   [ 62%]
tests/test_cors_security.py::test_cors_preflight_localhost_5173 PASSED   [ 75%]
tests/test_cors_security.py::test_cors_default_origins_are_localhost PASSED [ 87%]
tests/test_cors_security.py::test_cors_custom_origins_via_env PASSED     [100%]

8 passed in 0.26s
```
