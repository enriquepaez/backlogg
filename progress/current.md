# Sesión actual

Sin feature en curso. **FE-14 `session_ux` cerrada** (reviewer APPROVED,
`done` en `frontend_feature_list.json`), rama `feat/fe14-session-ux`. Ver
`progress/history.md` para el detalle completo. Pendiente: QA manual del
usuario en navegador y confirmación de ship (commit + push + PR a main).

El dev server (`pnpm --filter web dev` en `:3000`) y el backend (`:8000`)
quedaron corriendo al cierre de la sesión del implementer para esa QA;
usuario de prueba `fe14qauser` en la DB de dev.

## Siguiente feature disponible (M2)
**FE-15** `email_verification` (id=16, depende de [5, 6]).
**FE-16** `password_recovery` (id=17, depende de [5, 6]).
