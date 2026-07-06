# Verification — Cómo verificar que el trabajo está completo

> Una feature no está `done` hasta que `bash init.sh` termina en verde
> Y el reviewer la aprueba.

## Comando principal

```bash
bash init.sh
```

Este script ejecuta en orden:

1. **Comprobación del entorno** — verifica que Python y uv están disponibles.
2. **Comprobación de archivos del harness** — verifica que existen todos los
   archivos de infraestructura (`AGENTS.md`, `feature_list.json`, etc.).
3. **Validación de `feature_list.json`** — formato correcto, máximo 1 feature
   `in_progress` simultáneamente.
4. **Lint** (`uv run ruff check .`) — cero errores.
5. **Format check** (`uv run ruff format --check .`) — cero issues.
6. **Tests** (`uv run pytest --tb=short -q`) — todos en verde.

Salida esperada al final:
```
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Si cualquier paso falla, el script termina con código de salida != 0 y
**no debes declarar la tarea como `done`**.

## Verificación manual de un endpoint nuevo

Para cada endpoint nuevo, el leader presenta al usuario una checklist que cubre:

1. **Estado de DB** — tablas/filas vía psql:
   ```bash
   psql $DATABASE_URL -c "\d <table_name>"
   ```

2. **Endpoint happy path** — curl con respuesta esperada:
   ```bash
   curl -s http://localhost:8000/<path>/<slug> | jq .
   # Expected: HTTP 200, campos requeridos presentes
   ```

3. **Endpoint not found** — verificar 404:
   ```bash
   curl -o /dev/null -w "%{http_code}" http://localhost:8000/<path>/slug-inexistente
   # Expected: 404
   ```

4. **On-demand fallback** — slug no en DB pero sí en API externa:
   ```bash
   # 1. Verificar que el slug NO está en DB
   # 2. Hacer GET → debería persistir y devolver 200
   # 3. Verificar que el slug YA está en DB
   ```

## Backfill manual del catálogo

El sync nocturno vía `POST /admin/sync/{type}` está limitado por el timeout
de ~15 min por request de Render, por lo que avanza ~100 items/noche/tipo.
Para poblar el catálogo más rápido existe `scripts/backfill_sync.py`, que
reutiliza los mismos jobs de `backlogg/scheduler/jobs.py` pero escribe
directamente contra la DB (`DATABASE_URL`) y las APIs externas, sin pasar
por Render. El progreso se persiste en `sync_cursors` (compartido con el
nightly), así que re-ejecutarlo retoma donde quedó.

**Desde GitHub Actions (recomendado):**

1. Ir a *Actions → Backfill content sync → Run workflow*.
2. Elegir el tipo de contenido (`movie`/`series`/`book`/`game`) y lanzar.
   El input `seed_top_n` (default 10000) fija el objetivo de wraparound y
   **debe coincidir** con `SEED_TOP_N_*` en Render — si difiere, el cursor
   compartido `sync_cursors` haría wraparound antes de tiempo.
3. Repetir el dispatch hasta que el log termine con `stop_reason: wraparound`
   (objetivo alcanzado o API agotada). Una parada por `time_budget` (5 h por
   defecto) simplemente significa que hay que volver a lanzarlo.

Requiere los secrets `DATABASE_URL` (formato `postgresql+asyncpg://...`),
`TMDB_API_KEY`, `TWITCH_CLIENT_ID` y `TWITCH_CLIENT_SECRET`.

**En local:**

```bash
uv run python scripts/backfill_sync.py movie
uv run python scripts/backfill_sync.py game --slice-size 500 --time-budget-minutes 60
```

Usa el `DATABASE_URL` del entorno/`.env` — apunta a producción solo a
propósito. Defaults configurables también por env: `BACKFILL_SLICE_SIZE`
(500) y `BACKFILL_TIME_BUDGET_MINUTES` (300). Sale con código 0 en parada
normal (wraparound o presupuesto agotado) y != 0 si el tipo es inválido o
una iteración no consigue sincronizar nada.

## Variables de entorno requeridas

Copiar `.env.example` a `.env` y rellenar antes de correr tests de integración:

```bash
cp .env.example .env
```

Ver `docs/external-apis.md` para las variables requeridas por cada API externa.

## Base de datos de test

Los tests de repositorio usan una DB PostgreSQL real (separada de la de desarrollo).
La variable `TEST_DATABASE_URL` debe apuntar a una DB de test limpia.

Alembic aplica las migraciones automáticamente en la sesión de test
a través de `conftest.py`.
