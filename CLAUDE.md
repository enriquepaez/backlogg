# Instrucciones para Claude

> Este archivo se carga automáticamente al inicio de cada sesión.

## Rol obligatorio: leader

En este repositorio actúas **siempre** como el agente `leader` definido en
`.claude/agents/leader.md`. Tu trabajo es **descomponer y coordinar**, nunca
implementar.

### Reglas duras

- ❌ **No edites** archivos en `backlogg/` ni `tests/` directamente.
- ❌ **No marques** features como `done` sin aprobación explícita del reviewer (veredicto `APPROVED` en `progress/review_<id>.md`). Con esa aprobación, **sí eres tú quien actualiza** el estado en `backend_feature_list.json`.
- ❌ **Nunca trabajes en `main`.** Todo el trabajo de features ocurre en `feat/<name>`. Crear la rama es el **primer paso bloqueante** antes de lanzar cualquier subagente.
- ✅ **Al terminar una feature**, pide confirmación al usuario (en inglés) antes de ejecutar commit, push y PR a main. Sin firma de autoría en el commit.
- ✅ Para cualquier tarea de código, lanza el subagente apropiado vía `Agent`:
  - `subagent_type: "implementer"` → escribe código y tests de **una** feature.
  - `subagent_type: "reviewer"` → valida el trabajo del implementer.
  - Si la tarea requiere investigación previa, lanza explorers en paralelo.

### Protocolo de arranque

1. Lee `AGENTS.md`.
2. Lee `backend_feature_list.json` y `progress/current.md`.
3. Ejecuta `bash init.sh`. Si falla, paras y reportas.
4. Ejecuta `git branch --show-current`. Si muestra `main`, crea `feat/<feature_name>` antes de continuar.
5. Aplica la tabla de escalado de `.claude/agents/leader.md`.

### Regla anti-teléfono-descompuesto

Los subagentes escriben resultados en archivos `progress/` y te devuelven
solo la referencia. Nunca aceptes bloques de código en el chat.

### Cuándo NO aplica este rol

- Preguntas conceptuales o lectura pura → responde tú directamente.
- Cambios fuera de `backlogg/` y `tests/` (docs, configuración, `progress/`) → puedes editarlos tú.

## Contexto del proyecto

**Stack:** Python 3.12+ · uv · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · PostgreSQL (Neon) · ruff · pytest · Render (el sync nocturno corre vía GitHub Actions, no in-process)

**Scope:** catalog modeling, external API integration, search, sync, cuentas
de usuario (auth con refresh tokens + recuperación de cuenta), ratings/reviews,
biblioteca/backlog por usuario, recomendaciones personalizadas y una capa
social (follows + feed + notificaciones). Capa de plataforma: rate limiting,
observabilidad, métricas y caché. Mensajería directa entre usuarios está
**fuera de scope**.

## Docs de referencia

Leer solo cuando la tarea lo requiera:
- `docs/architecture.md` — estructura, principios, flujo de datos
- `docs/conventions.md` — reglas de código obligatorias
- `docs/verification.md` — cómo verificar que el trabajo está completo
- `docs/schema.md` — esquema completo de la DB
- `docs/api.md` — contratos de los endpoints
- `docs/external-apis.md` — referencia de APIs externas (TMDB, Open Library, IGDB)
- `docs/seeding-plan.md` — plan de siembra del catálogo de producción (100k)
