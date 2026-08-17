# Sesión actual

Sin feature en curso. En la rama `feat/user_avatar_upload`: feature 51
(`user_avatar_upload`, backend), FE-31 (`avatar_upload`, id 30, frontend),
el refinamiento `storage_s3_generalize`, el fix de `docker-compose.yml`
(bitnami/minio → minio oficial + `minio-init`) y el micro-fix de test
isolation (`R2_ENDPOINT_URL` en `tests/users/test_routes.py`) — todo
`done`/`APPROVED`/verificado, ver `progress/history.md` para el detalle
completo de cada uno.

`bash init.sh` en verde (838 tests). QA de backend 100% completo (curl+psql,
incluido el tramo 200/204 real contra MinIO). Usuario confirmó que la subida
funciona en su navegador. README.md y docs/operations.md documentan los
comandos de MinIO (dev) y la guía de Supabase Storage (prod).

Pendiente:
1. Confirmación explícita del usuario (en inglés) antes de commit/push/PR.
2. Supabase para producción — el usuario aún no ha creado el proyecto; no
   bloquea el PR (el código ya soporta cualquier S3-compatible vía
   `R2_ENDPOINT_URL`), solo falta rellenarlo en Render antes del deploy real.
