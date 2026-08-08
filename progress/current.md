# Sesión actual

Feature 33 `notifications` **completada y APROBADA** (rama `feat/notifications`).
Incluye fix del harness de tests preexistente (aislamiento por SAVEPOINT en
`tests/conftest.py`) que resolvió la flakiness de init.sh.

`feature_list.json` → status 33 = `done`. Resumen en `progress/history.md`.

**Pendiente:** QA manual + confirmación del usuario para ship (commit/push/PR).

Siguiente feature elegible por dependencias tras la 33:
- 34 personalized_recommendations (depende de 31, 28, 16 — todas done) ✅ elegible
- 35 auth_refresh_tokens (depende de 27 done) ✅ elegible
- 36 account_recovery (depende de 27 done) ✅ elegible
(La de menor id elegible es la 34.)
