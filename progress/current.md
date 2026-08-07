# Sesión actual

Sin feature en curso.

Épico social completo (features 1–30, todas `done`).

Roadmap ampliado el 2026-08-08 con 11 features nuevas (`pending`), agrupadas en tres bloques:

- **Producto:** 31 user_library (backlog want/in_progress/completed/dropped), 32 user_lists (colecciones curadas), 33 notifications, 34 personalized_recommendations.
- **Cuenta/seguridad:** 35 auth_refresh_tokens, 36 account_recovery (verificación email + reset password vía **Resend** tras interfaz EmailSender; fallback a log sin RESEND_API_KEY), 37 rate_limiting.
- **Plataforma/consumo:** 38 observability (logging estructurado + Sentry opcional), 39 metrics_endpoint (/metrics Prometheus), 40 response_caching (Cache-Control/ETag + caché TTL), 41 openapi_polish.

Scope actualizado en `docs/architecture.md` (principio 7) y `CLAUDE.md` para incluir los nuevos dominios; mensajería directa sigue fuera de scope.

Siguiente feature elegible por dependencias satisfechas: **31 user_library** (depende de 27, 2, 3, 4, 5 — todas `done`).
