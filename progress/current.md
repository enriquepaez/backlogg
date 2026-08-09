# Sesión actual

## FE-4 `auth_bff` — DONE (pendiente QA manual del usuario + ship)
- Rama `feat/fe4-auth-bff` (desde main con FE-3b mergeado, PR #79). Reviewer: **APPROVED**.
- FE-4 marcada `done` en `frontend_feature_list.json`. Resumen en `progress/history.md`. Temporales limpiados.
- Pipeline verde: `pnpm --filter web typecheck && lint && build` (exit 0). E2E del implementer contra backend real: los 9 escenarios OK.
- Cambios en working tree **sin commit** (a la espera de confirmación del usuario para commit/push/PR).

### SEGUIMIENTO para FE-5 (hallazgo no bloqueante del review)
- `session.ts` `safeSet/safeClear` tragan escritura de cookie en render RSC read-only. Si el access expira y se refresca DENTRO del render de un Server Component, el backend rota (revoca el refresh viejo) pero la cookie no se persiste → siguiente request = refresh revocado → backend lo trata como REUSE → revoca TODAS las sesiones.
- Hoy inofensivo (no hay página RSC protegida). **Resolver al montar FE-5** (primer consumidor de `getCurrentUser` en render): enrutar el refresh disparado desde RSC por Route Handler/Server Action que pueda persistir cookies.
- Cosmético: rama redundante en `apps/web/src/app/api/auth/login/route.ts:48`.

## Siguiente feature disponible (M0)
Con FE-4 `done`: **FE-5** app_shell (deps FE-3 ✅, FE-3b ✅, FE-4 ✅) y **FE-7** testing_ci (deps FE-2 ✅).
Orden natural M0 restante: FE-5 → FE-6 (pwa, deps FE-5) → FE-7.
