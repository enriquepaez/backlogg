# Sesión actual

## FE-2 `api_client` — COMPLETO (pendiente de ship)
- Rama `feat/fe2-api-client` (desde `main`). Reviewer: **APPROVED**. FE-2 `done` en `frontend_feature_list.json`.
- Paquete `packages/api-client` (`@backlogg/api-client`): tipos generados desde OpenAPI del backend
  (`openapi.json` 63 paths) + `openapi-typescript` (`src/schema.d.ts`) + factory `createApiClient`
  sobre `openapi-fetch` (`src/index.ts`) + ejemplo tipado GET `/v1/movies` (`src/example.ts`) +
  script `gen:api` (`scripts/gen-api.mjs`) + `README.md`.
- Wiring: dep `workspace:*` en `web`; typecheck raíz = `pnpm -r typecheck`. Build de Next intacto.
- Pipeline en verde: install, gen:api (determinista), typecheck (api-client+web), lint, build.
- Resumen movido a `progress/history.md`.

## Nota de entorno
- `bash init.sh` (pytest backend) falla por **Postgres local caído** (`pg_isready` no response;
  `systemctl postgresql` inactive). Irrelevante para features frontend. Para volver a correr el
  backend habrá que levantar Postgres (`TEST_DATABASE_URL`).

## Infra de dev incluida en el mismo commit (por petición del usuario)
- `docker-compose.yml`: `restart: unless-stopped` en `db` → la DB local revive tras reiniciar.
- `init.sh`: preflight `pg_isready` antes de pytest; si la DB está caída avisa con el remedio
  (`docker compose up -d && uv run alembic upgrade head`) en vez de 508 tracebacks. Verificado
  end-to-end: `bash init.sh` → 688 passed, "Entorno listo".

## Siguiente feature disponible (M0)
Con FE-2 `done`, quedan disponibles (deps satisfechas): **FE-3** design_system (deps FE-1),
**FE-3b** i18n (deps FE-1), **FE-4** auth_bff (deps FE-2), **FE-7** testing_ci (deps FE-2).
Orden natural: FE-3 → FE-3b → FE-4 → FE-5 (app_shell, deps FE-3/3b/4) → FE-6 → FE-7.
