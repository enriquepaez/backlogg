# Plan — Sistema propio de similitud y recomendación cross-type

> Estado: **diseño, sin implementar**. Sustituye la dependencia de
> `GET /movie/{id}/similar` y `/trending` de TMDB (ver
> `docs/source-migration-plan.md`) por un sistema propio que además cruza
> recomendaciones entre tipos de producto.

## El problema

Las tres señales de similitud actuales son **intra-tipo por construcción**:

| Señal | Dónde | Por qué no cruza tipos |
|---|---|---|
| Mismo autor / director | `books/service.py`, `credits` | Solo se consulta dentro del mismo `item_type` |
| Solapamiento de géneros | `*_genres_join` | Cuatro tablas de géneros distintas, cuatro taxonomías de proveedor que no se hablan |
| `similar` externo | TMDB | Solo existe para movies/series, y desaparece con la migración |

Los géneros son el obstáculo estructural: `movie_genres`, `series_genres`,
`book_genres` y `game_genres` son tablas independientes, pobladas desde
proveedores distintos. No hay identificador común entre "Fantasía" (Open
Library) y "Fantasy" (RAWG).

Lo que sí es transversal hoy: `people` + `credits`, que ya es polimórfica
sobre `MOVIE`, `SERIES`, `BOOK` y `GAME` (ver `docs/schema.md`).

## Arquitectura: cuatro capas y un ranker

Ninguna capa sirve sola. `/similar` y `/recommendations` consumen el ranker,
nunca una capa directamente.

```
                       ┌──────────────────────────────┐
   /similar  ────────► │  Ranker                      │
   /recommendations ─► │  · fusión con pesos por env  │
                       │  · cuota cross-type          │
                       │  · diversificación           │
                       │  · reason por candidato      │
                       └───────┬──────────────────────┘
                               │
        ┌──────────────┬───────┴───────┬──────────────────┐
        ▼              ▼               ▼                  ▼
   Capa 0         Capa 1          Capa 2             Capa 3
   Personas       Semántica       Conocimiento       Comportamiento
   (credits)      (embeddings)    (Wikidata)         (co-ocurrencia)
   ya existe      día 1           precisión          con masa crítica
```

---

### Capa 0 — Personas compartidas (la más barata, hazla primero)

`credits` ya enlaza los cuatro tipos contra la misma tabla `people`. Los roles
actuales, sin embargo, no permiten el cruce más obvio:

| Dominio | Roles hoy | Falta |
|---|---|---|
| Movies | DIRECTOR, ACTOR | **WRITER** |
| Series | CREATOR, ACTOR | **WRITER** |
| Books | AUTHOR | — |
| Games | (ninguno persistido) | DIRECTOR, WRITER |

**Añadir el rol `WRITER` a movies y series da el puente libro → película por
autor sin ninguna dependencia nueva.** Stephen King, Gaiman, Tolkien, Sapkowski:
el caso de uso cross-type más reconocible del producto, resuelto con una
migración y un cambio en el adaptador de ingesta.

- Coste: bajo. Ya hay tabla, índices y patrón de persistencia.
- Cobertura: limitada a obras con autoría cruzada, pero de altísima precisión.
- Bloqueante: la ingesta de créditos debe funcionar (issue #15).

---

### Capa 1 — Semántica: embeddings + pgvector

El puente natural entre tipos: **todo ítem tiene título, sinopsis y géneros**,
sea del tipo que sea. Se serializa a un párrafo, se embebe con un modelo
multilingüe y se guarda un vector por ítem. La similitud es coseno en un
espacio común, así que el cruce entre tipos es gratis por construcción.

**Modelo.** Debe ser multilingüe: las sinopsis llegan en español y en inglés
(la app es bilingüe). Opciones:

| Opción | Coste | Notas |
|---|---|---|
| OpenAI `text-embedding-3-small` | 0,02 $/M tokens | ~0,16 $ una vez para 40.000 ítems. Admite reducir dimensiones (`dimensions=512`) |
| BGE-M3 (MIT, local) | 0 € | 100+ idiomas, 8k de contexto. Requiere torch en el pipeline de ingesta |
| Jina embeddings | de pago | Especialmente fuerte en español-inglés según sus benchmarks |

**Recomendación: API en el pipeline de ingesta, no modelo local.** Ya tienes
`httpx` como dependencia; añadir torch/sentence-transformers metería cientos de
MB y presión de RAM en un VPS de 2 vCPU. El coste es despreciable.

**Punto clave de arquitectura: no hay inferencia en tiempo de petición.** El
vector se genera una vez al ingerir el ítem (job de sync/backfill, que corre en
GitHub Actions). Servir `/similar` es un lookup ANN contra un índice HNSW. Cero
latencia añadida, cero dependencia externa en el camino de la petición.

**Almacenamiento.** 40.000 ítems × 1536 dims × 4 bytes ≈ 245 MB. Con
`dimensions=512` baja a ~80 MB, y `halfvec` lo reduce a la mitad otra vez.
Relevante porque Neon cobra 0,35 $/GB-mes.

**Infra necesaria:**
- `docker-compose.yml`: cambiar `postgres:16` por `pgvector/pgvector:pg16`
  (la imagen oficial de Postgres no trae la extensión). Igual en CI.
- Neon soporta pgvector con `CREATE EXTENSION vector`, incluido índice HNSW.
- Migración Alembic: columna `embedding vector(512)` + índice HNSW por tabla,
  o una tabla `item_embeddings(item_type, item_id, embedding)` polimórfica —
  **preferible la segunda**, coherente con `credits` y `external_ids`, y evita
  cuatro índices HNSW separados.

**Limitación honesta:** capta "de qué va", no "a quién le gusta". Pondrá el
documental sobre la Segunda Guerra Mundial junto a la novela bélica. Por eso no
puede ser la única capa.

---

### Capa 2 — Conocimiento: adaptaciones vía Wikidata

Precisión quirúrgica, cobertura baja, valor percibido altísimo. Es la capa que
produce el "no sabía que había libro".

- `P144` (*based on*) y `P4969` (*derivative work*) enlazan explícitamente
  novela → película, película → videojuego, cómic → serie.
- Wikidata es **CC0**: sin problema comercial, coherente con el resto de la
  migración.
- Guarda los identificadores externos de TheTVDB, Open Library y RAWG, así que
  el mapeo contra tu catálogo es **por id, no heurístico**.

Implementación: volcado SPARQL periódico (mensual basta, estas relaciones no
cambian) → tabla `item_relations`:

```sql
item_relations (
    from_type, from_id, to_type, to_id,
    relation,   -- ADAPTATION | DERIVATIVE | COOCCURRENCE
    score,
    source      -- WIKIDATA | INTERNAL
)
```

La misma tabla la reutiliza la capa 3.

---

### Capa 3 — Comportamiento: co-ocurrencia en bibliotecas

La señal más potente para cruzar tipos, y la única que no se puede comprar:
**la biblioteca de un usuario ya abarca los cuatro tipos**. Item-item sobre
`library_entries` y `user_ratings`, coseno sobre la matriz ítem-usuario con
ponderación tipo BM25/TF-IDF para que la popularidad no aplaste todo.

- **Se activa por umbral, no por fecha.** Por debajo de ~1.000 usuarios con
  ~20 ítems cada uno la señal es ruido y empeora las recomendaciones. El
  ranker debe consultar el umbral y saltarse la capa mientras no se cumpla.
- Precomputada en batch (job nocturno en Actions), escrita en `item_relations`
  con `relation='COOCCURRENCE'`. Nada se calcula en tiempo de petición.

---

### El ranker

Lo que sirve `/similar` y `/recommendations`. No es una capa más: es la lógica
que las hace utilizables.

1. **Fusión con pesos configurables por env** (`REC_WEIGHT_SEMANTIC`,
   `REC_WEIGHT_PEOPLE`, `REC_WEIGHT_WIKIDATA`, `REC_WEIGHT_COOCCURRENCE`) —
   ajustables sin desplegar, mismo criterio que `RATE_LIMIT_*`.
2. **Cuota cross-type obligatoria.** De 10 resultados, al menos 3 de un tipo
   distinto al del ítem origen. Sin esta regla la capa semántica devuelve casi
   siempre el mismo tipo: los ítems de un mismo tipo comparten vocabulario
   («temporada», «jugador», «novela») y eso domina el coseno.
3. **Diversificación.** Penalización por franquicia/autor repetido, o MMR.
   Diez resultados de la misma saga no son diez recomendaciones.
4. **`reason` por candidato.** El campo ya existe en `RecommendationOut`. Cada
   capa aporta el suyo: «comparte autor con X», «es la novela en que se basa»,
   «a quien le gustó X también…». En recomendaciones cross-type la
   explicabilidad no es un adorno: es lo que hace que el usuario acepte que le
   ofrezcas un videojuego partiendo de una película.

---

## Trending: problema distinto, solución más simple

No necesita nada de lo anterior. `trending` es **actividad reciente en tu
propia plataforma**: `activity_events`, `library_entries` y `user_ratings` de
los últimos N días, con decaimiento temporal. En cuanto haya usuarios, tu
trending propio es mejor y más honesto que el de TMDB, porque refleja a tu
comunidad y no al tráfico global de otra web.

Mientras no haya usuarios, se cae a `rating_external × recencia` —
exactamente lo que ya hacen `type=book` y `type=game` hoy (ver
`docs/external-apis.md`). El parámetro `period`, que hoy se acepta y se
ignora para libros y juegos, pasa a tener efecto real para los cuatro tipos.

---

## Taxonomía unificada de temas (transversal)

Necesaria de todos modos, y no solo para recomendar: los filtros de la UI hoy
no pueden ofrecer un género común a los cuatro tipos.

### Hub, no pares

Mapear directamente "género del tipo A ↔ género del tipo B" son **seis** pares
de taxonomías (movie↔series, movie↔book, movie↔game, series↔book, series↔game,
book↔game), y cada tipo nuevo multiplica el trabajo. Con una tabla `themes`
intermedia cada taxonomía se mapea **una sola vez** contra el hub — cuatro
mapeos — y las seis combinaciones salen gratis. Añadir un quinto tipo (cómics,
música, pódcast) sería un mapeo más, no cinco.

El hub aporta además algo que el mapeo por pares no da: un vocabulario
**propio**, estable y traducible (es/en), que no se rompe cuando TheTVDB
renombre un género ni cuando vuelvas a cambiar de proveedor.

```sql
themes (
    id, slug,
    name_es, name_en,
    kind          -- THEME | FORMAT | MECHANIC
)

theme_mappings (
    provider,     -- THETVDB | OPEN_LIBRARY | RAWG
    item_type,    -- MOVIE | SERIES | BOOK | GAME
    source_genre, -- nombre o id del género en la taxonomía de origen
    theme_id
)
```

`theme_mappings` es **muchos-a-muchos por diseño**, no 1:1. Las taxonomías
reales traen géneros compuestos: "Action & Adventure" y "Sci-Fi & Fantasy" de
TMDB se rompen en dos temas cada uno, y un subject de Open Library puede
alimentar varios.

### Los tres `kind` no son un adorno

Es la distinción que hace que el mapeo funcione en vez de forzar equivalencias
falsas:

- **THEME** — eje temático, transversal a los cuatro tipos. Es el único que el
  ranker usa para cruzar tipos. Fantasía, Crimen, Romance, Bélico, Histórico.
- **FORMAT** — transversal pero no temático: Animación, Documental, Novela
  gráfica, Reality, Visual Novel. Peso bajo en el ranker; útil como filtro.
- **MECHANIC** — solo juegos: Plataformas, Puzzle, Carreras, Estrategia por
  turnos, Point-and-click. **No cruza tipos y no debe intentarlo.** Sirve para
  filtrar dentro de juegos y nada más.

### Lo que el mapeo manual sí y no va a resolver

Números reales del catálogo actual (370 libros, 547 películas, 309 series,
376 juegos ingeridos):

| Tipo | Géneros distintos | Naturaleza |
|---|---|---|
| Movies | 19 | Taxonomía cerrada y estable |
| Series | 14 | Taxonomía cerrada, con géneros compuestos |
| Games | 22 | Taxonomía cerrada, **mayoritariamente mecánicas** |
| **Books** | **510** | Folksonomía sin control |

**Movies, series y games: 55 entradas.** Una tarde de trabajo, y el resultado
es determinista y auditable. Aquí el mapeo manual es exactamente la
herramienta correcta.

**Games conecta mal, y hay que asumirlo.** De los 22 géneros de juego, solo
unos cinco cargan un tema transversal (Adventure, Music, Sport, y parcialmente
Fighting y Shooter vía Acción). El resto —Platform, Puzzle, Racing, RTS,
Pinball, Point-and-click, Turn-based strategy— son **mecánicas de juego, no
temas**, y no tienen equivalente en cine ni en literatura. El puente de los
juegos hacia los otros tipos no puede venir de los géneros: viene de los
embeddings, de las adaptaciones de Wikidata y de las personas.

**Books no se puede mapear a mano.** 510 etiquetas con solo 370 libros, y
**397 de ellas aparecen en un único libro**: "Triathlon", "Concentration
camps", "Country homes", "starvation", "Businesswomen". Con 10.000 libros
serán varios miles. Además hay duplicados semánticos evidentes —
Fantasy / Fantasy fiction, romance / Dark Romance / Contemporary Romance,
Biography / biographies — y mezcla de mayúsculas y minúsculas.

Tratamiento en tres pasos:

1. **Normalizar** antes de mapear nada: minúsculas, quitar el sufijo
   `" fiction"`, singularizar. Colapsa una parte notable de los duplicados
   por coste casi nulo.
2. **Mapear a mano la cabeza**: las ~100 subjects más frecuentes cubren la
   mayor parte del volumen real.
3. **Resolver la cola con embeddings**: embeber el nombre del subject y
   asignarlo al `theme` más cercano por coseno, con umbral de confianza. Lo que
   no pase el umbral se queda sin tema, y para ese ítem la similitud la aporta
   el embedding de la sinopsis. Es justo el problema para el que la capa 1 es
   mejor herramienta que una tabla.

### Por qué merece la pena aunque exista la capa semántica

Los embeddings ya capturan el parecido temático, así que el mapeo podría
parecer redundante. No lo es:

- Es **determinista y auditable**: cuando alguien reporte que algo no es
  Terror, lo corriges en una fila, no reentrenas nada.
- Da **filtros de UI**, que los embeddings no dan. "Fantasía" pasa a ser
  navegable en los cuatro tipos.
- Produce un **`reason` legible**: «porque también es Fantasía». En un salto de
  película a videojuego, esa frase es lo que hace que el usuario acepte la
  recomendación en lugar de leerla como un error.
- Es la **señal de respaldo** cuando falta la sinopsis, frecuente en libros de
  Open Library (ver `docs/external-apis.md`).

Entra en el ranker como capa propia, con su peso (`REC_WEIGHT_THEMES`).

### Secuenciación: hazlo después de la migración, no antes

Los 19 géneros de movies y los 14 de series de la tabla de arriba **son de
TMDB**. TheTVDB tiene su propia taxonomía (unos 35 géneros según el enum de
`/movies/filter` en su swagger), así que mapear ahora significa hacer el
trabajo dos veces. Games igual: el mapeo debe hacerse contra la taxonomía de
RAWG, no contra la de IGDB.

Orden correcto: migrar fuentes → volcar las taxonomías reales de TheTVDB y
RAWG → mapear a mano contra el hub.

---

## Orden de implementación

Encaja con la migración de fuentes; los pasos 1 y 2 son los que sustituyen a
TMDB `/similar`.

| # | Feature | Depende de |
|---|---|---|
| 0 | Rol `WRITER` en credits de movies y series | issue #15 |
| 1 | pgvector + `item_embeddings` + generación en el pipeline de ingesta | migración de fuentes |
| 2 | `/similar` reescrito sobre capa semántica + cuota cross-type | 1 |
| 3 | Taxonomía unificada `themes` + mapeos | migración de fuentes |
| 4 | Adaptaciones vía Wikidata → `item_relations` | — |
| 5 | Ranker sobre las capas 0–2 en `/recommendations` | 0, 2, 4 |
| 6 | `/trending` propio sobre actividad local | — |
| 7 | Co-ocurrencia en `item_relations` (activada por umbral) | 5, masa crítica de usuarios |

## Cautela legal

Los términos de TMDB prohíben expresamente entrenar sistemas de IA con sus
datos. Generar embeddings es inferencia sobre contenido que tienes licencia
para mostrar, no entrenamiento, pero es zona gris. Tras la migración la
pregunta se traslada a TheTVDB y RAWG: **revisar sus términos en busca de
cláusulas sobre IA/ML antes de generar embeddings sobre sus sinopsis.**
