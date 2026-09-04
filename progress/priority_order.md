# Orden de prioridad del backlog

> A diferencia de `progress/current.md`, este archivo **no se trunca** al cerrar
> sesión — sobrevive entre sesiones. Actualízalo (no lo vacíes) cuando cambien
> las prioridades o se complete algo de la lista.

**Mientras este archivo tenga entradas pendientes, úsalo en vez del criterio por
defecto de `AGENTS.md` §4** («coge la de menor id con dependencias
satisfechas»). Ese criterio por defecto **daría una respuesta equivocada hoy**:
elegiría la feature 74, que está bloqueada de facto por el issue #15.

## ⚠️ Una tarea cada vez

**Se ejecuta un único punto de esta cola a la vez, y no se empieza el siguiente
hasta que el anterior está mergeado.** El ciclo completo por punto es:

```
rama feat|fix|chore/<name>  →  implementer  →  reviewer (APPROVED)
  →  QA manual del leader  →  confirmación del usuario  →  commit + push + PR
  →  merge a main  →  siguiente punto
```

Esto ya es la regla del proyecto (`one_feature_at_a_time: true` en
`backend_feature_list.json` y en `frontend_feature_list.json`, y `AGENTS.md`
§5), y se repite aquí porque es la que más fácil se rompe cuando hay una cola
larga delante. **No agrupes dos puntos en una rama ni abras un PR con dos
features dentro.** La única excepción admitida es la ya registrada en memoria:
un bug encontrado durante la QA de la feature X se arregla en la rama de X,
aunque su causa esté en otro sitio.

Si un id de aquí ya no está en `pending` en `backend_feature_list.json`,
sáltalo — no hace falta editar este archivo solo por eso.

Al terminar la lista entera, **bórrala siguiendo el apartado «Cómo desmontar
esto» del final**.

---

## Estado (2026-09-04)

> Contado contra los tres archivos fuente, no de memoria. Si vuelves a tocar
> esta sección, vuelve a contarlos.

- **12 features backend pendientes**: 74-83, 87 y 88. Ninguna en `in_progress`.
  Las 84, 85 y 86 están `done`.
- **5 features frontend en `blocked`** (FE-65 a FE-69, ids 64-68): ninguna
  ejecutable hoy, cada una espera a su feature backend pareja. Las 63 anteriores
  están `done`. Índice en el apartado «Frontend».
- **7 issues abiertos**: #15, #18, #19, #20, #23, #24 y #25. El **#22 pasó a
  `resolved` el 2026-09-04**; los #23, #24 y #25 nacieron de su arreglo. Detalle y
  ubicación en la cola justo debajo.

### Issues abiertos y dónde caen en la cola

| Issue | Sev. | Dónde está en la cola |
|---|---|---|
| **#20** `uq_external_id` sin `item_type` | high | **Punto 3.1 — hecho**: implementado, revisado y con QA manual el 2026-09-04, en la rama `fix/uq_external_id_item_type`. Sigue `open` a propósito: no se cierra hasta medirlo contra producción, para no repetir el error que originó el #15 |
| **#22** saltos silenciosos sin contador ni log | high | **Punto 3.2 — hecho y `resolved`**: implementado, revisado (APPROVED) y con QA manual el 2026-09-04, en la rama `fix/external_ids_skipped_link_observability`. A diferencia del #20, este sí se cierra: la instrumentación es el entregable y se verificó contra un salto real |
| **#23** duplicado huérfano por renombrado en la fuente | medium | **Sin punto asignado todavía.** Es el mecanismo que de verdad dispara el salto: medido en la QA del #22 con datos reales. Decidir si entra antes de la siembra —cuando la siembra lo dimensione— o después |
| **#24** colisión de slug en `_resolve_people` pierde un id de persona | low | **Sin punto asignado.** Falso negativo del contador del #22; emparenta con el #18 (el slug haciendo de identidad cuando no puede) |
| **#25** `_unlinked_targets_stmt` no comprueba `item_id` | medium | **Sin punto asignado.** Acoplado a la decisión del #23: reabrir los targets sin cambiar «gana el primero» sería peor que el estado actual |
| **#18** slug vacío en alfabetos no latinos | high | **Punto 3.3 — antes de sembrar.** Decisión de producto pendiente: transliterar vs. derivar el slug del external_id |
| **#15** credits vacíos en el catálogo | high | **Sus dos mitades están resueltas en el papel, pero sigue `open` a propósito** (ver más abajo): movies/series/books se disuelve con el borrado —que aún no se ha ejecutado— y games se **podó** el 2026-09-04 |
| **#19** flake de `DeadlockDetectedError` | low | **Sin punto asignado, y es una decisión consciente.** No bloquea nada y no corrompe datos; el coste es CI rojo intermitente que entrena a ignorar un `init.sh` rojo. Se aborda cuando moleste |

> **El issue #15, sus dos mitades.** Su parte operativa —«hay que correr el
> backfill de credits contra Neon»— **desaparece con el borrado**: una siembra
> desde cero escribe los credits durante la propia hidratación
> (`append_to_response=credits`), así que no hay hueco que rellenar después.
>
> La otra mitad —**games no tiene ningún código que persista credits**, solo que
> los lee— se **podó el 2026-09-04 por decisión del usuario**. Era una intención
> del arranque del proyecto que nunca se implementó. El motivo de podarla y no
> construirla: IGDB v4 **no expone credits de persona en absoluto** (todos sus
> endpoints de autoría son de empresa), así que habría hecho falta una fuente
> nueva —Wikidata tras la 79, o MobyGames— para un dato pobre en casi todas las
> fuentes, cuyo único valor real es el puente cross-type juego ↔ película por
> director compartido: apuesta de producto, no requisito.
>
> Se llegó a dar de alta como feature backend 89 y frontend FE-70 ese mismo día,
> y ambas se **borraron** al podarla. Lo que queda como rastro permanente es la
> corrección de los documentos, que es donde importaba: `docs/schema.md` ya no
> promete un rol `DIRECTOR` para games —la tabla de roles pone `(none)` y explica
> por qué— y `docs/external-apis.md` corrige la nota falsa «director data is
> sparse — only sync when available». Games conserva sus **company credits**
> (`DEVELOPER`/`PUBLISHER`), que son otra tabla y no se tocan.
>
> **Por qué el issue sigue `open` con las dos mitades resueltas**: el borrado y
> la siembra **todavía no se han ejecutado**. Cerrarlo ahora repetiría
> exactamente el error que lo originó — el issue #7 se cerró dando por hecho un
> backfill que nunca se corrió. Se cierra cuando la siembra esté hecha y medida.

---

> **Actualización 2026-09-04 — producción se borra y se siembra desde cero.**
> El usuario confirmó que producción no tiene datos reales, solo de prueba, y que
> puede borrarse por completo. Tres consecuencias sobre esta cola:
>
> 1. **El issue #21 queda resuelto sin escribir código** (residuo de ítems
>    huérfanos irreparables): si la base se recrea con el esquema ya arreglado,
>    esos ítems no llegan a existir.
> 2. **El borrado es una fecha límite, no un atajo.** Resetea los datos, no el
>    código: todo defecto que hoy pierde datos en silencio se hornearía en el
>    catálogo nuevo, esta vez sobre 118.850 ítems. Es la única ocasión en la que
>    no hay que reparar nada, porque se construye limpio.
> 3. Por eso **los issues #18 y #22 entran antes de la siembra**, entre el
>    arreglo del #20 y la feature 87. Ambos son pérdida silenciosa de datos:
>    #18 descarta los credits de nombres en alfabeto no latino (mucho contenido
>    CJK y cirílico entra con `vote_count >= 25`, y credits es el dato sobre el
>    que corren las features 74 y 82); #22 es la ausencia de contador/log en los
>    dos caminos de escritura de `external_ids` — el mecanismo que ya encadenó
>    los issues #7, #15 y #20, y el único panel de instrumentos durante una
>    siembra de varias horas.
>
> El borrado y la siembra de producción se ejecutan **como paso propio**, con
> confirmación explícita del usuario, no dentro de otra tarea.

## Orden acordado con el usuario (2026-09-02)

El razonamiento de fondo: **primero el catálogo, después lo que se construye
encima.** Todas las features de recomendación (74-83) operan sobre el catálogo;
construirlas sobre un catálogo parcial, con el 79% de las películas sin credits,
es construir sobre arena. Y hay una razón mecánica además de la estratégica: la
feature 75 embebe el catálogo entero, así que hacerla antes de sembrarlo obliga
a re-embeberlo después.

Diseño completo del bloque de catálogo en **`docs/seeding-plan.md`**.

### Bloque A — Fundación del catálogo

| # | Feature | Por qué aquí |
|---|---|---|
| 1 | **84** `bulk_load_pipeline` | Prerrequisito duro de 85, 86 y 87. Además es **condición necesaria** para la ventana de caché de 6 meses de TMDB: con 57.135 movies hacen falta 318/noche frente a los 200 de `SYNC_SLICE_SIZE`, y a 3,1 s/ítem eso excede el tope de ~15 min de Render (`docs/seeding-plan.md` §2.3) |
| 2 | **85** `backfill_credits_targeted` | Cierra el **issue #15**, que es lo que bloquea la 74. Sin esto la capa 0 de recomendación no tiene datos |
| 3 | ~~**86** `tmdb_discover_quality_seeding`~~ ✅ **done 2026-09-03** | El catálogo real de movies/series (`vote_count ≥ 25` → 57.135 + 10.880). Rompe el techo de 10.000 de `/popular` |
| 3.1 | **issue #20** `uq_external_id` gana `item_type` | ✅ implementado, revisado y con QA manual el 2026-09-04. Prerrequisito duro: sin él la siembra pierde catálogo en silencio y a tasa creciente |
| 3.2 | ~~**issue #22** hacer ruidosos los saltos silenciosos de `external_ids`~~ ✅ **resolved 2026-09-04** | Era el panel de instrumentos de la siembra. `skipped_links` viaja ya del job al endpoint, al `backfill_sync.py` y al `::warning::` del workflow nocturno |
| 3.3 | **issue #18** slug de nombres en alfabeto no latino | Antes de sembrar: si no, el catálogo nuevo nace con un agujero permanente en credits. Decisión de producto pendiente (transliterar vs. `tmdb-<id>`) |
| 4 | **87** `openlibrary_dump_seeding` | El catálogo real de books (18.874). Saca `search.json` del camino crítico |
| 5 | **74** `credits_source_author_role` | **Aquí y no antes**: necesita el issue #15 resuelto (paso 2) y las *dos orillas* del puente sembradas — movies/series del paso 3 y books del paso 4. Y aquí y no después: la 86 reescribe la hidratación con `append_to_response=credits`, que es exactamente el payload del que sale `SOURCE_AUTHOR`; hacerla con ese código fresco evita tocar dos veces el mismo bucle de `crew` |
| 6 | **88** `catalog_incremental_updates` | Cierra el ciclo. Sin esto el catálogo se congela el día de la siembra: ni entran estrenos ni promocionan los ítems que cruzan el umbral de `vote_count` a posteriori |

### Bloque B — Capa semántica y de conocimiento

A partir de aquí el orden coincide con el numérico y todas las dependencias
quedan satisfechas en secuencia.

| # | Feature | Nota |
|---|---|---|
| 7 | **75** `pgvector_item_embeddings` | Ya **no está bloqueada**: el riesgo de la cláusula de IA de TMDB se aceptó explícitamente el 2026-09-02 (`docs/external-apis.md`). Va después del bloque A para embeber el catálogo definitivo una sola vez |
| 8 | **76** `themes_taxonomy` | Hub cross-type |
| 9 | **77** `themes_manual_mapping` | `depends_on: [76, 72✓]` |
| 10 | **78** `themes_longtail_autoassign` | `depends_on: [77, 75]` |
| 11 | **79** `wikidata_adaptations` | Independiente. Doble propósito: también es el ancla de QID frente a un cambio futuro de proveedor |
| 12 | **80** `similar_semantic_rewrite` | `depends_on: [75]` |

### Bloque C — Endpoints propios

| # | Feature | Nota |
|---|---|---|
| 13 | **81** `trending_local` | Independiente |
| 14 | **82** `recommendations_ranker` | `depends_on: [74, 76, 79, 80]` — todas satisfechas al llegar aquí |
| 15 | **83** `cooccurrence_layer` | `depends_on: [82]`, **y además masa crítica de usuarios**. Es legítimo que se quede en `pending` indefinidamente: sin usuarios no hay co-ocurrencia que medir |

---

## Frontend

**No hay ninguna feature de frontend *ejecutable* hoy** (estado a 2026-09-04):
63 de las 68 entradas de `frontend_feature_list.json` están en `done` — la
última, FE-64 `item_detail_field_ordering` — y las rutas de
`apps/web/src/app/[locale]/` cubren ya todo lo que expone el backend actual.

Las **5 restantes están `blocked`**, no `pending`: son trabajo real y contado,
solo que ninguna puede arrancar todavía. Ninguna feature backend de esta cola ha
pasado a `done` desde que se escribieron, así que las cinco siguen bloqueadas.

Lo que sí hay es **el frontend que van a generar las features backend de esta
cola**. Está en `frontend_feature_list.json` como **5 entradas con status
`blocked`** (FE-65 a FE-69, ids 64-68), no aquí: esta tabla es solo el índice.
Cada una se desbloquea cuando su feature backend pareja pasa a `done`, y
entonces se ejecuta como punto propio de la cola — misma regla de una tarea cada
vez, su propia rama y su propio PR.

| Desbloquea | Frontend | Entrada |
|---|---|---|
| backend **74** `credits_source_author_role` | Mostrar y etiquetar `SOURCE_AUTHOR` y `WRITER` en la sección Credits | **FE-65** `credits_source_author_writer_display` |
| backend **79** `wikidata_adaptations` | Sección «basado en / adaptado a» en la ficha | **FE-66** `item_detail_adaptations_section` |
| backend **80** `similar_semantic_rewrite` | Presentar la cuota cross-type en `/similar` | **FE-67** `similar_cross_type_presentation` |
| backend **81** `trending_local` | `period` efectivo en `/trending` para books y games | **FE-68** `trending_period_books_games` |
| backend **82** `recommendations_ranker` | Mostrar el `reason` por candidato | **FE-69** `recommendations_reason_display` |

FE-68 no es especulación sino **deuda ya registrada**: la feature backend 68 se
cerró el 2026-08-26 con la nota «sin frontend pareja todavía», y hoy
`period=day/week` se acepta para book y game pero no tiene ningún efecto.

Las features 76-78 (`themes`) podrían generar frontend también —navegación por
tema cross-type—, pero eso es una decisión de producto que no está tomada: no
hay entrada creada y no cuenta como deuda hasta que se decida.

---

## Fuera de este backlog

Nota estratégica registrada el 2026-08-29 y que sigue vigente: **la prioridad
real antes de salir a producción no está en esta lista.** No la pierdas de vista
al elegir tarea:

- Páginas legales (no existe ninguna).
- Nombre y dominio.
- Salir del free tier de Render (hoy prod duerme, cold start ~50 s).
- Ejecutar la siembra de verdad contra producción una vez estén las 84-88.

Y el recordatorio del mismo día: las recomendaciones cross-type son el
diferencial del producto, pero **con cero usuarios no se pueden evaluar**. El
bloque A tiene valor desde el día uno; los bloques B y C no lo tendrán hasta que
haya gente usando la app.

---

## Cómo desmontar esto

Cuando las 12 features backend pendientes estén `done` (o se descarten) **y no
queden issues con punto asignado en la cola**, **borra todo rastro de este
orden** — son tres sitios, ninguno más:

1. **Borra este archivo**: `rm progress/priority_order.md`.
2. **Revierte el override en `AGENTS.md` §4**: elimina el bloque
   `> **Override activo**: …` que hay justo debajo del recuadro de «Cómo elegir
   una tarea». Con eso el criterio vuelve a ser el de por defecto (menor id con
   dependencias satisfechas), que para entonces será correcto.
3. **Borra la línea de `progress/history.md`** que apunte a este orden, si se
   añadió alguna.

El apartado «Frontend» se puede borrar con el resto sin perder nada: sus cinco
filas son solo un índice de FE-65 a FE-69, que viven en
`frontend_feature_list.json` y no dependen de este archivo para existir.

Lo que **no** hay que borrar, porque no es «orden de ejecución» sino
documentación permanente del proyecto: `docs/seeding-plan.md`, las entradas de
`backend_feature_list.json`, el diagnóstico del issue #15 en `issues_list.json`
y las referencias a `docs/seeding-plan.md` en `AGENTS.md` §2 y `CLAUDE.md`.
