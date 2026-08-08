# Sesión actual

## Tanda de pulido backend (pre-frontend)

Todas las 41 features del scope original están `done`. El usuario decidió cerrar
loose ends de backend antes de arrancar el frontend (que será **Next.js + React + TS**).

Features nuevas en backlog (`feature_list.json`), a ejecutar en orden. **Versionado al final**
(decisión del usuario: sellar `/v1` cuando el backend inicial esté completo, no a mitad):

| id | feature | qué cierra | paths en dev | depende de |
|----|---------|-----------|--------------|------------|
| 42 | `account_deletion` | `DELETE /users/me` con cascada + recomputo de agregados. | raíz | 27 |
| 43 | `review_reports` | Tabla `review_reports` + endpoint usuario + cola admin. | raíz | 28 |
| 44 | `content_moderation` | `is_hidden` en reviews + `is_banned` en users; enforcement. | raíz | 43, 28 |
| 45 | `api_versioning` | Barrido final: TODO bajo `/v1`; `/health` y `/metrics` sin versionar. | — | 42,43,44 |

### Modo de ejecución (autorizado por el usuario)
Ejecución **autónoma** de las 4 features, sin confirmación intermedia. Por cada feature:
rama `feat/<name>` → implementer → reviewer → **QA manual hecha por el leader** → commit (sin firma)
→ push → PR. **NO se mergea** ningún PR; el usuario mergea todo al final en orden 42→43→44→45.
PRs **apilados**: cada rama sale de la anterior y su PR apunta a la rama padre (diff limpio por PR).

### Decisiones de diseño ya fijadas
- **Versionado el último** por semántica limpia: un único barrido mecánico sella el backend inicial como v1.
- **Corte limpio** en el versionado: no hay clientes en producción, no se mantienen rutas raíz.
- **42**: la cascada DB ya existe (todos los FKs a `users.id` son `ON DELETE CASCADE`), pero hay que
  recomputar `rating_internal`/`rating_count_internal` de los items puntuados (la cascada no lo hace).
  Reutilizar `ratings.repository.recalculate_item_aggregates()`.
- **44**: los agregados deben excluir reviews ocultas (añadir `WHERE is_hidden = false` al recompute).
  Ban engancha en `users.service.login_user` (service.py:99) y en el flujo de refresh.
- **Moderación** se decidió incluir (el usuario la pidió explícitamente); no es solo remate.

### Estado
- [x] 42 account_deletion — APPROVED + QA 11/11. PR #69.
- [x] 43 review_reports — APPROVED + QA 13/13. PR #70 (base feat/account_deletion).
- [x] 44 content_moderation — APPROVED + QA 18/18. PR pendiente de abrir (base feat/review_reports).
- [ ] 45 api_versioning

En curso: cerrando la 44 (commit/push/PR), luego arranco la 45 (barrido /v1 final).
