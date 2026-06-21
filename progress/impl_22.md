# Implementación feature #22 — cors_and_security

## Archivos modificados

- `backlogg/main.py` — añadidos CORSMiddleware y SecurityHeadersMiddleware

## Archivos creados

- `tests/test_cors_security.py` — 8 tests que verifican todos los acceptance criteria

## Qué se implementó

### backlogg/main.py

Se añadieron dos middlewares después de `app = FastAPI(...)`:

1. **SecurityHeadersMiddleware** (BaseHTTPMiddleware): añade tres headers de seguridad a toda respuesta:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `Referrer-Policy: strict-origin-when-cross-origin`

2. **CORSMiddleware** de FastAPI: lee `CORS_ORIGINS` del entorno (comma-separated). Si no está configurada, permite `http://localhost:3000` y `http://localhost:5173`. Configurado con `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`.

**Orden de add_middleware (LIFO):** SecurityHeadersMiddleware se registra primero (`add_middleware` en orden 1) y CORSMiddleware segundo (orden 2). En Starlette el stack es LIFO, por lo que CORSMiddleware envuelve a SecurityHeadersMiddleware — el CORS se procesa primero (incluyendo preflights), y luego los security headers se añaden a la respuesta en la fase de salida. Esto garantiza que los headers de seguridad están presentes incluso en respuestas CORS.

### tests/test_cors_security.py

Tests con `TestClient` síncrono (no AsyncClient), ya que estos tests no requieren DB:

- `test_security_headers_present` — verifica los 3 headers de seguridad en GET /health
- `test_cors_allowed_origin_localhost_3000` — Origin 3000 recibe Access-Control-Allow-Origin
- `test_cors_allowed_origin_localhost_5173` — Origin 5173 recibe Access-Control-Allow-Origin
- `test_cors_disallowed_origin` — Origin externo no recibe el header CORS
- `test_cors_preflight_localhost_3000` — OPTIONS devuelve 200 + headers CORS para 3000
- `test_cors_preflight_localhost_5173` — OPTIONS devuelve 200 + headers CORS para 5173
- `test_cors_default_origins_are_localhost` — sin env var, ambos localhost están permitidos

## Output de bash init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.5
[OK]    uv -> uv 0.11.16

── 2. Verificando archivos base del harness ────────────
[OK]    (todos los archivos base presentes)

── 3. Validando feature_list.json ──────────────────────
[OK]    feature_list.json válido (22 features)

── 4. Lint (ruff) ──────────────────────────────────────
[OK]    ruff check pasa
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
185 passed in 227.61s (0:03:47)
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo.
```
