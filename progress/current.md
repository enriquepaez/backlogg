# Sesión actual

**Feature en curso: 89 `credits_people_storage_redesign`** (punto 6 de
`progress/priority_order.md`). Rama `feat/credits_people_storage_redesign`,
creada el 2026-09-07 desde `main` al día. `bash init.sh` en verde antes de
empezar (1448 tests).

## Plan

1. **Medir primero** — criterio de aceptación 1. La consulta está escrita y
   lista; espera la `DATABASE_URL` de producción, que no está en el repo (ver
   «Credenciales» abajo). Lo que mide: distribución de `people` por número de
   credits, reparto de credits por rol, cuántas personas existen solo como
   reparto de ficha, y el tamaño actual de `credits` / `people` /
   `external_ids` con sus índices.
2. **Decidir A vs B con esos números** y registrar la decisión por escrito
   (criterio 2). A = estrechar tipos (`item_type`/`role` a smallint, quitar el
   `id` autoincremental). B = separar ficha (JSONB en la fila del ítem) del
   grafo. A es casi gratis dentro de B.
3. **Implementer** — no antes del paso 2.
4. Reviewer → QA manual del leader → confirmación → commit/push/PR.

## Estado: medición hecha, decisión tomada, implementer en marcha

**Medición ejecutada contra producción el 2026-09-07** → informe completo en
`progress/measure_89.md` (criterios 1, 2 y 10). Titulares:

- El grafo de personas es **266 MB de los 484** de la base: el 55 %.
- **El 46,9 % de `people` son actores con una sola aparición** en todo el
  catálogo (112.832 personas).
- Proyección a catálogo completo (119.225 ítems): modelo actual **~626 MB**,
  solo A **~579 MB**, **A+B ~444 MB**. El techo es 512.

**Decisión (criterio 2): A + B, las dos.** El argumento no es que B ahorre más,
sino que **A sola no cabe** — deja la base 67 MB por encima del techo, así que
no desbloquea la siembra, que es el único motivo por el que la feature existe.

Se midió y **se descartó** una variante intermedia (conservar navegables a los
actores con N+ apariciones): recorta el eje equivocado. Con umbral 2 borra el
47 % de las personas y solo el 16 % de los credits, porque el volumen de filas
vive en los actores prolíficos.

Decisiones de diseño cerradas con el usuario (§11 del informe): reparto en
**tabla lateral `item_cast`**, y **`GET /people/{slug}` se mantiene** con dos
comportamientos a documentar (404 para actores de solo-reparto; 200 sin credits
ACTOR para las 9.251 personas que dirigen/escriben y además actúan).

Hallazgo extra de la medición: `character_name` y `billing_order` los usan
**solo** las filas ACTOR, así que ambas columnas se borran de `credits`.

**Implementer lanzado.** Escribirá en `progress/impl_89.md`. Después: reviewer,
QA manual del leader (incluida la medición del ahorro real contra Neon, que el
implementer no puede hacer por no tener credenciales), confirmación del usuario
y PR.

## Contexto que sigue vigente de la sesión anterior

**La feature 74 está en `in_progress` a propósito.** Código implementado,
revisado, con QA y mergeado en el PR #197. Su criterio 9 depende de la siembra,
que bloquea la 89. La 74 y el issue #15 se cierran juntos.

**Producción tiene un catálogo a medias y no se toca**: movies 56.371 de 57.166
· books 19.159 · games 10.000 (topado) · **series 0**. La siembra murió por el
techo de 512 MB de Neon. No se reintenta hasta que la 89 esté hecha.

## Credenciales: dónde NO están

La `DATABASE_URL` de producción **no está en `.env`** (esa apunta al contenedor
local `backlogg-db`). Vive en el dashboard de Neon, en las variables de Render y
en el secret de GitHub Actions, que es de solo escritura. Hay que pedírsela al
usuario.

Detalle que cuesta un intento: está guardada con prefijo `postgresql+asyncpg://`,
que es dialecto de SQLAlchemy. **`psql` no lo entiende** — hay que quitarle el
`+asyncpg`.

⚠️ La contraseña de producción quedó escrita en el historial de la conversación
del 2026-09-07. **Pendiente de rotar** en Neon, actualizando después el secret de
GitHub Actions y la variable de Render.
