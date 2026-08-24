# Audit 4 — Síntesis (2026-08-25)

Seguimiento a `progress/audit3_synthesis_2026-08-24.md`. El usuario confirmó
que las 7 tareas de audit3 (backend 61-63, frontend FE-51..FE-54) están
`done`, y pidió repasar los tres audits anteriores, volver a auditar, y dar
un veredicto honesto sobre producción — señalando la sensación de estar
"dando vueltas sobre lo mismo".

## Método (deliberadamente distinto de audit2/audit3)

No se relanzó el patrón de dos/tres subagentes `general-purpose` releyendo
`backlogg/`/`apps/web/` de cabo a rabo. Motivo: audit2 encontró 2 HIGH,
audit3 encontró 0 HIGH (solo MEDIUM/LOW) — la severidad ya converge a cero
con ese método. Repetirlo una cuarta vez sobre el mismo código, sin cambios
sustanciales de por medio, iba a reproducir exactamente la sensación que el
usuario describe. En su lugar:

1. Verificación de estado real: `backend_feature_list.json` y
   `frontend_feature_list.json` — 0 items con `status != done` en ambos.
   `issues_list.json` — 0 issues abiertas.
2. `bash init.sh` (987 tests backend) + `typecheck`/`lint`/`test` en
   frontend (1054 tests) — todo verde.
3. Verificación puntual, con grep/lectura directa, de los 4 "notas sin
   feature formal" que audit3 dejó anotadas pero sin tarea asociada — para
   comprobar si de verdad se habían resuelto o si simplemente nadie las
   había tocado.
4. Un pase nuevo, no cubierto por audit1/2/3: superficie **no-código** de
   production readiness (páginas legales, config de CORS en ausencia de
   env var, verificación cruzada docs↔código).

## Veredicto: el código está listo; el proyecto no, todavía

Las 7 tareas de audit3 están implementadas de verdad (no stubs), tests
verdes en ambos lados, cero deuda técnica pendiente en los backlogs. Un
quinto audit de código con el mismo método casi seguro no encontraría nada
accionable — **la razón real de la sensación de bucle no es que el código
siga roto, es que las notas sueltas de audit3 nunca se cerraron** y por
tanto seguían ahí para volver a encontrarlas hoy:

- `render.yaml` sigue sin declarar `ADMIN_API_KEY`, `CORS_ORIGINS`,
  `SMTP_*`, `R2_*`, `SENTRY_DSN` — confirmado leyendo el archivo tal cual.
  Un deploy nuevo desde el Blueprint las deja sin configurar. Con
  `CORS_ORIGINS` vacío el fallback es `localhost:3000`/`5173` (falla cerrado,
  no es un agujero de seguridad, pero **rompe la comunicación
  frontend↔backend en producción real** hasta que se añada a mano).
- `docs/operations.md` sigue describiendo `RATE_LIMIT_AUTH` como si
  cubriera solo login/register; confirmado en código
  (`backlogg/users/routes.py`) que protege 7 endpoints (incluye logout,
  verificación de email, forgot/reset password) desde la feature 56/61.
  Doc desactualizada, sin impacto funcional.
- `LogoutButton` sigue presente en `apps/web/src/components/` — código
  muerto documentado como deliberado, no se ha borrado.
- `SITE_URL` sigue cayendo a `http://localhost:3000` por defecto
  (`apps/web/src/lib/env.ts:53`) si no se fija en el hosting del frontend.

Ninguno de estos 4 puntos es nuevo — son exactamente los mismos 4 que
quedaron anotados hace un día. Nadie los marcó `pending` como feature
formal porque son ajustes de una línea, y por eso no entran en el flujo de
`implementer`/`reviewer` — pero tampoco se hicen solos. Ese es el patrón de
bucle real: cosas triviales que quedan fuera del sistema de tracking se
quedan sin hacer indefinidamente.

## Hallazgo nuevo (no cubierto por audit1/2/3): páginas legales

No existe página de privacidad ni de términos de servicio en
`apps/web/src/app/[locale]/` (verificado por búsqueda exhaustiva), ni
enlace a ninguna en el footer/nav. La app registra cuentas con email y
password, envía correos transaccionales y guarda datos personales
(username, avatar, actividad) — para un lanzamiento público real esto es
uno de los pocos bloqueantes que no es "deuda técnica", es requisito
mínimo antes de aceptar el primer registro de un usuario real (más aún
operando desde España/UE). Ningún audit anterior lo cubrió porque los tres
se enfocaron en código (`backlogg/`, `apps/web/`), no en superficie legal.

## Recomendación

No hace falta un audit 5 de código. Hace falta cerrar lo que ya se sabe
que falta:

1. Los 4 ajustes de una línea de audit3 (render.yaml + 3 más) — bloquean
   un deploy limpio desde cero, no bloquean el código que ya corre.
2. Página mínima de privacidad/términos — bloqueante real de lanzamiento
   público, no técnico.
3. Después de eso: **no relanzar el bucle de audit genérico**. Si en el
   futuro hace falta otra vuelta, que sea sobre un cambio concreto (nueva
   feature grande, cambio de infra) en vez de una relectura completa del
   repo — el método de "leer todo otra vez" ya dio de sí lo que tenía que
   dar en 3 rondas.

Nada de esto se ha implementado. Queda a la espera de que el usuario
decida si quiere cerrar estos puntos antes de lanzar o aceptar el riesgo
conocido y lanzar igualmente.
