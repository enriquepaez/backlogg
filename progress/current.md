# Sesión actual

Fecha: 2026-08-06
Rama: feat/users_auth (shipped, PR #50 abierta, pendiente de merge)

## Épico: capa social (auth, ratings/reviews, follows, feed)

Feature 27 (users_auth) implementada, revisada (APPROVED) y shippeada:
https://github.com/enriquepaez/backlogg/pull/50

Bloqueado: feature 28 (ratings_reviews) depende del código de F27
(modelo User, get_current_user) y no puede arrancar su rama desde `main`
hasta que la PR #50 esté mergeada.

### Incidente de deploy — resuelto al mergear

El QA local corrió `alembic upgrade head` contra la Neon de producción (el
`.env` local apunta a la misma DB, no hay Postgres local) — la tabla `users`
y `alembic_version='0009'` ya existen en prod. Al añadir `JWT_SECRET_KEY` en
Render, el redeploy automático de `main` (sin la PR #50 mergeada, código solo
hasta migración 0008) chocó con la DB ya en `0009` → `Can't locate revision
identified by '0009'`. Sin riesgo de datos: se resuelve mergeando la PR (deja
`main` en el mismo estado que la DB) y dejando que Render redeploya.
`render.yaml`/`docs/operations.md` actualizados con `JWT_SECRET_KEY` en el
mismo commit.

Detalle completo del plan del épico en
`/home/enriquepaez/.claude/plans/luminous-finding-hickey.md`.
