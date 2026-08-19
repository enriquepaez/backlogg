# Audit 2 — Síntesis (2026-08-19)

Seguimiento a `progress/audit_ux_2026-08-18.md`. El usuario pidió repasar si
las 13 tareas propuestas hace dos días se cumplieron y buscar mejoras nuevas
antes de salir a producción.

Método: tres auditorías en paralelo — `progress/audit2_backend_2026-08-19.md`
(verificación de features 52-55 + pase de production readiness sobre
`backlogg/`), `progress/audit2_frontend_2026-08-19.md` (verificación de
FE-36 a FE-44 + pase de production readiness sobre `apps/web/`), y
`progress/audit2_walkthrough_2026-08-19.md` (QA en vivo). No se reintroduce
el dominio de listas curadas — descartado explícitamente por el usuario en
el audit original, sigue fuera de scope.

## Veredicto: las 13 tareas se cumplieron

Las 4 features de backend (52-55) y las 9 de frontend (FE-36..FE-44) están
implementadas correctamente contra sus criterios de aceptación originales,
no como stubs — verificado leyendo el código real (no solo el flag `done`),
con `bash init.sh` en verde (939 tests backend) y `typecheck`/`lint`/`test`
en verde en frontend (1041 tests). El walkthrough en vivo confirmó además
que el resultado se ve y funciona bien de extremo a extremo: el enlace a
biblioteca (el hallazgo principal del audit original) es ahora visible y
está a un clic en el header, los colores de estado son sólidos y vivos, el
acento de marca + tipografía de titulares se ve intencional, y el rating
widget/activity log funcionan.

## Hallazgos nuevos, priorizados

Se han creado 5 tareas nuevas en `backend_feature_list.json` (ids 56-60) y 6
en `frontend_feature_list.json` (FE-45..FE-50), todas en `pending`, mismo
formato que siempre. Recomendación de priorización antes de salir a
producción:

### Antes de lanzar (recomendado)

- **56 `auth_recovery_rate_limiting`** (backend, HIGH) — recuperación de
  cuenta sin rate limit; riesgo real de agotar el cupo diario de SMTP
  (~500/día en Gmail) o de enumeración de cuentas por temporización.
- **57 `notification_fanout_batching`** (backend, HIGH) — fan-out secuencial
  de notificaciones bloquea la respuesta de completar un item; riesgo de
  timeout en Render free tier con muchos followers.
- **FE-45 `profile_seo_metadata`** (frontend, HIGH) — perfiles públicos sin
  `generateMetadata`; la superficie más compartible del producto no tiene
  título/OG propio.
- **FE-46 `sitemap_robots`** (frontend, HIGH) — falta `sitemap.ts`/`robots.ts`
  para un catálogo pensado explícitamente para SEO.

### Puede esperar a después del lanzamiento

- **58 `banned_user_immediate_revocation`** (MEDIUM) — ventana de hasta 15
  min donde un usuario baneado conserva escritura.
- **59 `admin_key_constant_time_compare`** (MEDIUM) — comparación no
  tiempo-constante del API key de admin.
- **60 `library_entries_composite_index`** (MEDIUM) — índice compuesto para
  el patrón de consulta más común de biblioteca; inofensivo al volumen
  actual.
- **FE-47 `rating_accessibility_labels`** (MEDIUM) — estrellas de solo
  lectura invisibles para lectores de pantalla en 4 sitios.
- **FE-48 `personal_widgets_query_refactor`** (MEDIUM) — deuda técnica: 4
  widgets reimplementan el mismo patrón fetch en vez de usar TanStack Query,
  ya documentado como obligatorio en `docs/frontend-plan.md`.
- **FE-49 `avatar_next_image`** (LOW) — avatares sin `next/image`.
- **FE-50 `activity_log_delete_confirm`** (LOW) — falta confirmación al
  borrar una entrada de activity log.

Nada de esto se ha implementado — quedan en `pending` a la espera de que el
usuario elija por cuál empezar, igual que en el audit original.
