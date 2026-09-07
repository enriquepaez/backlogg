# Feature 89 — Medición contra producción (criterios de aceptación 1, 2 y 10)

Ejecutada el 2026-09-07 contra la base de producción en Neon.
Estado del catálogo medido: **85.530 ítems** — movies 56.371, books 19.159,
games 10.000 (topado), **series 0**. Base total: **484 MB de 512 MB**.

> ⚠️ Todos los credits de persona del catálogo actual salen de **movies**
> (55.590 fichas con reparto) y de **books** (AUTHOR). Series aporta **cero**
> porque no llegó a sembrarse. Las proyecciones a catálogo completo de este
> informe extrapolan el coste de series desde el de movies; es la única cifra
> del informe que no está medida, y está marcada como tal.

## 1. Punto de partida

| Tabla | Total | Tabla | Índices | Filas |
|---|---|---|---|---|
| `credits` | 136 MB | 61 MB | 74 MB | 710.772 |
| `external_ids` | 74 MB | 24 MB | 50 MB | 328.350 |
| `people` | 56 MB | 30 MB | 26 MB | 240.615 |
| **Suma** | **266 MB** | | | |

266 MB de 484 = **el 55 % de la base es el grafo de personas**, para 85.530
ítems. Confirma el diagnóstico que motivó la feature.

De las 328.350 filas de `external_ids`, **242.822 (74 %) son de personas**
(229.105 TMDB + 13.717 Open Library). Solo 85.528 son de ítems del catálogo.

## 2. Distribución de `people` por número de credits — criterio 1

| Credits | Personas | % personas | Credits | % volumen |
|---|---|---|---|---|
| 1 | 143.763 | 59,75 % | 143.763 | 20,23 % |
| 2 | 37.069 | 15,41 % | 74.138 | 10,43 % |
| 3-5 | 33.162 | 13,78 % | 122.321 | 17,21 % |
| 6-10 | 14.683 | 6,10 % | 110.107 | 15,49 % |
| 11+ | 11.938 | 4,96 % | 260.443 | 36,64 % |

**Casi 6 de cada 10 personas del catálogo aparecen una sola vez.** No hay
personas huérfanas (con 0 credits): el tramo no existe.

La forma de la distribución es la que anticipaba la feature, pero con un matiz
que resulta decisivo más abajo: **el volumen de filas está concentrado en el
extremo opuesto al de las personas.** El 4,96 % más prolífico concentra el
36,64 % de los credits.

## 3. Qué es ficha y qué es grafo

| Rol | Credits | % | Personas distintas |
|---|---|---|---|
| ACTOR | 517.600 | 72,82 % | 184.557 |
| WRITER | 90.744 | 12,77 % | 39.888 |
| DIRECTOR | 61.899 | 8,71 % | 23.402 |
| AUTHOR | 26.359 | 3,71 % | 13.717 |
| SOURCE_AUTHOR | 14.170 | 1,99 % | 7.516 |

| Clase | Personas | % | Credits | % |
|---|---|---|---|---|
| Solo ACTOR (ficha pura) | 175.306 | 72,86 % | 457.505 | 64,37 % |
| Construye grafo | 65.309 | 27,14 % | 253.267 | 35,63 % |

**112.832 personas —el 46,9 % de toda la tabla `people`— son actores con un
único credit en todo el catálogo.** Cada una paga fila en `people` (125 B),
fila en `external_ids` (73 B), fila en `credits` (86 B) y su parte en siete
índices, a cambio de cero valor de navegación y cero valor de recomendación.

## 4. Coste medido de los defectos de tipos (opción A)

Medido con `pg_column_size`, no estimado:

| Concepto | Coste actual | Tras estrechar | Ahorro |
|---|---|---|---|
| `item_type` VARCHAR(20) | 4.139 kB | 1.388 kB (smallint) | 2,7 MB |
| `role` VARCHAR(50) | 4.571 kB | 1.388 kB (smallint) | 3,1 MB |
| Columna `id` (sin FKs) | 5.553 kB | 0 | 5,4 MB |
| Índice `credits_pkey` | 15 MB | 0 (`uq_credit` pasa a PK) | 15 MB |
| Índice `uq_credit` | 35 MB | ~20-27 MB | 8-15 MB |
| `idx_credits_item` | 7.616 kB | ~6 MB | 1,6 MB |
| `idx_credits_role` | 4.504 kB | ~3 MB | 1,5 MB |

**A deja `credits` en ~97-100 MB desde 136. Ahorro ~36-39 MB.**

Nota sobre `uq_credit`: reordenar la clave a `(item_id, person_id, item_type,
role)` evita el relleno de alineación que impone empezar por un `smallint`
seguido de dos `bigint`. Es la diferencia entre ~27 MB y ~20 MB, gratis.

## 5. Coste medido de separar ficha de grafo (opción B)

Con B, `credits` y `people` conservan **solo** DIRECTOR, WRITER, AUTHOR y
SOURCE_AUTHOR; el reparto se desnormaliza a JSONB.

- `credits`: 710.772 → **193.172 filas (27,2 %)**
- `people`: 240.615 → **65.309 filas (27,1 %)**
- `external_ids`: se borran **175.306 filas** (todas PERSON/TMDB), el 53,4 % de
  la tabla. Las 13.717 de Open Library se conservan íntegras: son autores.
- **Payload JSONB medido: 34 MB** para los 517.600 credits ACTOR, a 69 B por
  actor y **9,31 actores de media por película** (máx. 30, p95 10).

Ese payload es el dato que hace viable a B: **642 B por ficha de media, muy por
debajo del umbral de TOAST de ~2 kB**, así que se guarda inline y sin comprimir.
No hay lectura extra ni descompresión al pintar la página de detalle.

## 6. La variante intermedia, medida y descartada

Antes de decidir se midió una variante B′ que conservaba navegables a los
actores con N o más apariciones, dejando el JSONB llevar siempre el reparto
completo. La intuición era comprar de vuelta «otras obras de este actor» barato.
**Los números dicen que no es barata:**

| Umbral | `people` que quedan | `credits` que quedan |
|---|---|---|
| ≥2 apariciones | 53,1 % | **83,6 %** |
| ≥3 | 43,0 % | **76,4 %** |
| ≥5 | 35,7 % | **67,4 %** |
| B pura | 27,1 % | **27,2 %** |

**El umbral no sirve porque recorta el eje equivocado.** Conservar a una persona
navegable obliga a conservar *todas* sus filas de credits, y el volumen de filas
vive precisamente en los actores prolíficos (§2: el 4,96 % concentra el 36,64 %).
Con umbral 2 se borra el 47 % de las personas y solo el 16 % de los credits —
y `credits` es la tabla de 136 MB, la que hay que reducir. B′ paga complejidad
por un ahorro que se evapora.

## 7. Proyección a catálogo completo — criterio 11

Catálogo objetivo de `docs/seeding-plan.md`: 119.225 ítems (57.166 movies,
10.880 series, 19.221 books, 31.958 games). Sobre el catálogo actual eso es
+20 % de credits, +18 % de personas y +25 % de `external_ids`; el resto de la
base escala con su propio número de ítems (`catalog_search` 105 → ~146 MB,
games ×3,2 por la feature 90, series desde cero, etc.).

| Escenario | Grafo de personas | Base completa | ¿Cabe en 512 MB? |
|---|---|---|---|
| Modelo actual | ~321 MB | **~626 MB** | ❌ **114 MB por encima** |
| Solo A | ~274 MB | **~579 MB** | ❌ **67 MB por encima** |
| **A + B** | **~139 MB** | **~444 MB** | ✅ **cabe, ~68 MB de margen** |

## 8. Decisión — criterio 2

**Se implementan A y B, las dos.**

El argumento no es que B ahorre más, sino que **A sola no cabe**: deja la base
proyectada 67 MB por encima del techo, así que no desbloquea la siembra, que es
el único motivo por el que esta feature existe. A se implementa igualmente
porque, una vez abierta la migración de `credits`, es casi gratis, y porque su
ahorro se multiplica por B (estrechar filas que además son un 27 % menos).

Descartadas con números, no por intuición: **A sola** (§7, no cabe) y **B con
umbral** (§6, recorta el eje equivocado).

## 9. Lo que B cuesta, dicho claro

Se pierde la navegación **«otras obras de este actor»** para los 175.306 actores
que solo son reparto. Se conserva íntegro: el reparto completo en la ficha (el
JSONB lo lleva entero, no se recorta a los primeros N), la navegación por
director, creador y autor, y **todo el puente cross-type de la feature 74** —
`AUTHOR` y `SOURCE_AUTHOR` son roles de grafo y no los toca B.

**Hoy esa pérdida no es una regresión visible**: `apps/web` no enlaza a ninguna
página de persona, y `frontend_feature_list.json` no tiene ninguna feature que
lo planee — está escrito explícitamente en el comentario de cabecera de
`apps/web/src/components/item-credits.tsx`. Lo que sí cambia es el endpoint
público `GET /people/{slug}`, que pasará a devolver 404 para esos actores.

Si algún día se quiere recuperar, la vuelta no es cara en código pero sí en
disco: una tabla de enlace estrecha `(person_id, item_type, item_id)` cuesta
~35 MB, y volver a materializar las filas de `people` y `external_ids` cuesta
los ~80 MB que B ahorra. Es una decisión a revisar al salir del free tier, no
una puerta de un solo sentido: la re-hidratación regenera esas filas.

## 10. Dos avisos para quien implemente

**`idx_people_name` (8.952 kB, `idx_scan` = 0) no se borra.** Producción no ha
tenido tráfico de usuarios desde el borrado, solo la siembra: el 0 significa «la
siembra no lo usó», no «la app no lo usa». Con B cae solo a ~2,4 MB por el
recorte de filas, que es suficiente. Lo mismo aplica a
`idx_catalog_search_vector` y a `uq_catalog_search_type_id`.

**`catalog_search` es la siguiente pared.** Hoy son 105 MB y proyecta a ~146 MB,
lo que la convierte en el objeto más grande de la base en cuanto esta feature
aterrice. No es alcance de la 89 y el margen de §7 ya la contempla, pero el
margen de 68 MB depende de que esa proyección se cumpla. Conviene volver a
medirla después de la siembra.

---

## 11. Decisiones de diseño cerradas con el usuario (2026-09-07)

### 11.1 El reparto vive en una tabla lateral `item_cast`

No en una columna de `movies`/`series`. El motivo es el perfil de acceso: la
ficha lee el reparto, pero búsqueda y trending recorren `movies` entera sin
tocarlo. Ensanchar cada fila 642 B (un +40 % sobre las 40 MB de `movies`)
encarece esos barridos a cambio de ahorrar un lookup por PK en la ficha.

```sql
CREATE TABLE item_cast (
  item_type smallint NOT NULL,
  item_id   bigint   NOT NULL,
  payload   jsonb    NOT NULL,
  PRIMARY KEY (item_type, item_id)
);
```

El payload es un array ordenado por `billing_order` con nombre, personaje y
orden. **No se recorta**: la ficha sigue mostrando el reparto completo.

### 11.2 `GET /people/{slug}` se mantiene

Se descartó retirarlo. Retirar la ruta **no libera un solo byte**, que es el
único problema que esta feature resuelve; sería una decisión de producto
viajando dentro de una migración de almacenamiento, contra la regla de una
feature por rama. Y lo que sobrevive a B es justo lo que da valor al endpoint:
las 65.310 personas de grafo conservan **todos** sus credits, así que la
filmografía de un director o un autor sigue completa.

Además la feature 82 lo va a necesitar: sus `reason` son «comparte autor con X»
y «es la novela en que se basa», y FE-69 los pinta. Enlazar esa persona es el
paso siguiente natural.

También se descartó **mantener el contrato completo con un índice GIN** sobre el
payload: devuelve 30-40 MB de los 68 de margen del §7 para sostener un contrato
que hoy no consume nadie.

**Los dos comportamientos que hay que documentar en `docs/api.md`** — el segundo
es el que sorprende, y no debe descubrirse en la QA:

| Caso | Personas | Respuesta |
|---|---|---|
| Actor de solo-reparto | 175.306 | **404** |
| Persona de grafo que además actúa | **9.251** | **200**, pero sin sus credits ACTOR (60.095 en total) |

El segundo es el caso Clint Eastwood: su filmografía como director queda
completa, sus papeles como actor desaparecen de la respuesta.

**No cambia el esquema de la respuesta**: `CreditOut` mantiene su forma y solo
llegan menos elementos en el array. Por tanto **no dispara el criterio 8**
(regenerar `packages/api-client` + `pnpm typecheck`); sí exige sincronizar
`bruno/` y documentar lo de arriba.

### 11.3 Alcance cerrado

**A + B**, tabla lateral `item_cast`, `/people` intacto. `apps/web` no se toca:
no enlaza a páginas de persona y `ItemCredits` seguirá recibiendo el reparto
completo por el mismo contrato de los endpoints de detalle.
