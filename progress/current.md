# Sesión actual

Sin feature en curso.

## Nota: FE-31 avatar_upload sigue bloqueada
`depends_on: [18]` satisfecho, pero requiere un endpoint de subida/almacenamiento
de archivos en el backend que no existe en `feature_list.json` todavía
(avatar_url sigue siendo VARCHAR de solo texto). No retomar hasta que exista
esa feature de backend.

## Nota: FE-34 admin_catalog_backoffice en pausa
Trabajo completo y aprobado en `stash@{0}` ("wip: FE-34 admin_catalog_backoffice")
sobre la rama `feat/admin_catalog_backoffice`, pendiente de recuperar
(`git stash pop`) tras mergear la feature 50 (`catalog_search_filters`) y
extender el admin con los nuevos filtros de búsqueda antes de dar la feature
por definitivamente terminada.
