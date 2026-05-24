# Review — Feature 5: Games

**Veredicto:** APPROVED

## Checkpoints

- C1: [x] — `bash init.sh` termina sin errores (código de salida 0).
- C2: [x] — No hay `print()` de debug en el código nuevo.
- C3: [x] — No hay TODOs sin contexto en el código nuevo.
- C4: [x] — `ruff check` y `ruff format --check` pasan sin errores.
- C5: [x] — 47 tests pasan.
- C6: [x] — Modelos usan SQLAlchemy 2.0 (`Mapped`, `mapped_column`, `select()`, `AsyncSession`).
- C7: [x] — La migración 0005 encadena desde 0004 y no recrea tablas anteriores.
- C8: [x] — La migración incluye `upgrade()` y `downgrade()` completamente implementados.
- C9: [x] — El route handler `get_game` es `async` y usa `Depends(get_db)`.
- C10: [x] — `response_model=GameOut` es un schema Pydantic v2.
- C11: [x] — URL es `GET /games/{slug}`, sin IDs numéricos.
- C12: [x] — Si IGDB retorna None, el servicio lanza `HTTPException(404)`.
- C13: [x] — `test_get_game_returns_200` cubre el happy path del endpoint.
- C14: [x] — `first_release_date` (Unix timestamp) se convierte explícitamente con `datetime.fromtimestamp(int(ts), tz=UTC).date()`.
- C15: [x] — Slugs únicos por test: `-repo`, `-endpoint`, `-service` suffixes. Ningún test comparte el mismo slug.
- C16: [x] — El fallback persiste el item vía `repo.upsert_game` antes de devolverlo; confirmado en `test_get_game_fallback_to_igdb` que verifica la persistencia.
- C17: [x] — Si la API externa retorna None, devuelve 404.
- C18: [N/A] — Solo aplica a feat 8 (scheduler).
- C19: [N/A] — Solo aplica a feat 8 (scheduler).
- C20: [x] — `routes.py` delega enteramente a `service.get_game`; sin lógica propia.
- C21: [x] — `service.py` no contiene queries SQLAlchemy; usa `repo.*` como frontera.
- C22: [x] — La respuesta pasa por `response_model=GameOut` (Pydantic v2); el ORM no se expone directamente.

## Hallazgos

Ninguno. La implementación es conforme a todas las convenciones y la arquitectura definida.

## Detalles

- Separación de capas correcta: `routes.py` sin lógica, `service.py` sin queries SQLAlchemy, `repository.py` como única frontera de persistencia.
- El `IGDBClient` con renovación automática de token Twitch (buffer de 60s) es limpio y cubierto por tests unitarios en `test_igdb_client.py`.
- La conversión Unix timestamp → `date` es explícita en `adapters/igdb.py` línea 125: `datetime.fromtimestamp(int(ts), tz=UTC).date()`.
- La normalización de rating (0-100 → 0-10) es correcta y testeada.
- La migración `0005_games.py` crea todas las tablas requeridas por `docs/schema.md`: `game_genres`, `games`, `game_genres_join`, `game_platforms`, `game_platforms_join`, `companies`, `company_credits`. Los índices GIN, triggers `updated_at`, y constraints `UNIQUE` coinciden con el schema.
- El modelo ORM en `models.py` está completamente alineado con `docs/schema.md`.
- `GameOut` en `schemas.py` incluye todos los campos definidos en `docs/api.md` para `GET /games/{slug}`: `id`, `title`, `original_title`, `slug`, `overview`, `release_date`, `game_type`, `original_language`, `poster_url`, `backdrop_url`, `rating_external`, `rating_count_external`, `genres[]`, `platforms[]`.
- Los 4 archivos de test cubren: repositorio (real DB), servicio (IGDB mockeado), endpoint (HTTPX AsyncClient) y cliente IGDB (token + mapeo).
- El patrón de `HTTPException` en `service.py` es consistente con los otros dominios del proyecto (movies, series, books).

## Output de init.sh

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.4
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe feature_list.json
...

── 4. Lint (ruff) ──────────────────────────────────────
All checks passed!
[OK]    ruff check pasa
67 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
...............................................          [100%]
47 passed in 56.92s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```
