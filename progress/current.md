# Sesión actual

**Estado: sin tarea en curso.** La última sesión cerró el 2026-09-07 dejando
todo mergeado. Lo que sigue es el contexto que una sesión nueva necesita y que
no se deduce del código ni del historial de git.

## Por dónde seguir

`progress/priority_order.md` → **punto 6: feature 89
`credits_people_storage_redesign`**. Lee antes el bloque «Actualización
2026-09-07» de ese archivo: explica por qué la 89 se coló delante de la 88.

Su **criterio de aceptación 1 no es implementar, es medir**: la distribución
real de `people` por número de credits contra producción. La decisión entre
estrechar tipos (A) y separar ficha de grafo (B) sale de ese número. No arranques
un implementer sin él.

## Dos cosas que parecen incoherentes y no lo son

**1. La feature 74 está en `in_progress` a propósito.** Su código está
implementado, revisado (`APPROVED`), con QA manual y **mergeado** en el PR #197.
No está `done` porque su criterio de aceptación 9 —«issue #15 verificado como
resuelto para movies, series **y** books»— depende de la siembra de producción,
que está bloqueada por la 89. La 74 y el issue #15 se cierran **juntos** cuando
la siembra esté hecha y medida. Cerrarla antes repetiría el error del issue #7,
que se dio por cerrado dando por hecho un backfill que nunca se corrió.

**2. Producción tiene un catálogo a medias, y no se toca.** movies 56.371 de
57.166 · books 19.159 · games 10.000 (topado) · **series 0**. La siembra murió
por el techo de 512 MB del free tier de Neon. **No se reintenta hasta que la 89
esté hecha**: volver a llenar con el modelo actual choca con la misma pared.
Cuando se retome, no se repite nada — los 795 movies pendientes siguen en
`seed_targets` y la fase `load` de books es idempotente.

## Credenciales: dónde NO están

La `DATABASE_URL` de **producción no está en `.env`**. La de `.env` apunta al
contenedor Docker local (`backlogg-db`). La de producción vive solo en el
dashboard de Neon y en las variables de Render, y en el secret `DATABASE_URL` de
GitHub Actions —que es de solo escritura: `gh` da el nombre, nunca el valor—.
Para cualquier consulta contra producción hay que pedírsela al usuario.

Detalle que cuesta un intento: esa URL está guardada con el prefijo
`postgresql+asyncpg://`, que es el dialecto de SQLAlchemy. **`psql` no lo
entiende**; hay que quitarle el `+asyncpg`.

⚠️ La contraseña de producción quedó escrita en el historial de la conversación
del 2026-09-07. **Pendiente de rotar** en Neon, actualizando después el secret de
GitHub Actions y la variable de Render. Si se rota antes de la siembra, el
workflow deja de autenticar a mitad.
