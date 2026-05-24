# Historial de sesiones

<!-- Append-only. Añadir una línea al cerrar cada feature. -->
<!-- Formato: YYYY-MM-DD | feat_<id> <name> | resumen de una línea -->
2026-05-24 | feat_1 shared_models | pyproject.toml + core (config, database) + shared/models.py (Person, Credit) + shared/external_ids.py (ExternalId, helpers upsert/get/set) + migración Alembic 0001 (external_ids, people, credits con triggers) + 5 tests en verde.
