# Issues detectados en QA — 2026-06-21

Análisis manual de todos los endpoints del backend.
Estado base: 179 tests ✅, init.sh verde ✅, 4 tipos de contenido en DB.

---

## Issue 1 — Credits vacíos en todo el contenido del seed

**Severidad:** Alta  
**Estado:** ✅ Resuelto (2026-07-04) — desbloqueado por Issue 6 (PR #37); el re-sync completo se ejecuta ahora cada noche vía workflow (PR #39) y puebla people/credits

### Síntoma
Todos los items sincronizados en el seed inicial tienen `credits: []`.  
- 253 películas → credits vacíos  
- 241 series → credits vacíos  
- 112 juegos → credits vacíos  
- La tabla `people` está vacía para el contenido seedeado

Solo el contenido ingirido **después** via on-demand fallback tiene créditos  
(e.g., Blade Runner 2049 al hacer GET /movies/blade-runner-1982 tiene Ryan Gosling, Harrison Ford, etc.).

### Causa
El sync inicial (que pobló la DB) se ejecutó antes de que la feature #6 (people) y #21 (credits in detail) estuvieran implementadas. Las funciones `_persist_movie_people`, `_persist_series_people`, `_persist_game_companies` existen en el código, pero nunca se ejecutaron contra el contenido actual de la DB.

### Solución
Ejecutar un re-sync completo via los endpoints admin:
```
POST /admin/sync/movie
POST /admin/sync/series
POST /admin/sync/game
```
Esto hace upsert idempotente de todo el contenido + pobla people y credits.  
Los libros no tienen créditos por spec (autores sí via #19, pero se necesita verificar).

### Verificación
Tras el sync, `GET /movies/{slug}` de cualquier película seedeada debería devolver `credits[]` no vacío.  
`GET /admin/stats` debería mostrar `last_synced_at` actualizado.

---

## Issue 2 — On-demand fallback de movies ignora el año del slug

**Severidad:** Media  
**Estado:** ✅ Resuelto (PR #38)

### Síntoma
`GET /movies/blade-runner-1982` devuelve **Blade Runner 2049 (2017)** en lugar de Blade Runner (1982).

### Causa
El fallback extrae solo el título del slug (stripping dígitos y guiones):  
`"blade-runner-1982"` → search TMDB por `"blade runner"` → toma el primer resultado (más popular = Blade Runner 2049).

La función `_title_from_slug` en `backlogg/movies/service.py` descarta el año.

### Solución
Pasar el año al TMDB search cuando esté disponible en el slug.  
TMDB acepta `primary_release_year` como parámetro en `/search/movie`.

```python
# En _title_from_slug o en get_movie, extraer el año del slug
# y pasarlo como year_filter a _tmdb.search_movie(query, year=year)
```

### Verificación
`GET /movies/blade-runner-1982` debe devolver la película de Ridley Scott (1982), no Blade Runner 2049.

---

## Issue 3 — On-demand fallback de games no funciona

**Severidad:** Media  
**Estado:** ✅ Resuelto (PR #38)

### Síntoma
`GET /games/doom-1993`, `GET /games/minecraft` devuelven 404.  
El fallback de games nunca encuentra nada porque busca por slug exacto en IGDB.

### Causa
`IGDBClient.get_game_by_slug(slug)` hace:
```
where slug = "doom-1993";
```
Pero IGDB usa sus propios slugs (`doom`, `minecraft`, `the-last-of-us`) que no siempre coinciden con los slugs internos del sistema (que añaden año).

Movies y series resuelven esto con title-search. Games solo tiene búsqueda por slug exacto de IGDB.

### Solución
Añadir fallback de búsqueda por título cuando `get_game_by_slug` devuelve `None`:
1. Extraer el título del slug (igual que movies)  
2. Llamar a `IGDBClient.search_games(title_from_slug)` 
3. Tomar el primer resultado con más `rating_count`

```python
# En backlogg/games/service.py get_game()
raw = await _igdb_client.get_game_by_slug(slug)
if raw is None:
    # fallback: buscar por título
    title = _title_from_slug(slug)
    results = await _igdb_client.search_games(title, limit=1)
    raw = results[0] if results else None
if raw is None:
    raise HTTPException(status_code=404, detail="Game not found")
```

### Verificación
`GET /games/doom-1993` debe devolver Doom (o el más cercano), `GET /games/minecraft` debe devolver Minecraft.

---

## Issue 4 — Géneros de libros son tags crudos de Open Library

**Severidad:** Baja  
**Estado:** ✅ Resuelto (PR #38)

### Síntoma
Los géneros de libros incluyen strings como:
- `"American fiction (fictional works by one author)"`
- `"Long island (n.y.), fiction"`
- `"Married people, fiction"`
- `"Lectures et morceaux choisis"` (francés)
- `"Traffic accidents"`

Son subjects de catalogación bibliográfica de Open Library, no géneros legibles para un usuario.

### Causa
El adapter de Open Library usa los `subjects` del work sin normalización ni filtrado.

### Solución
Opciones (de menor a mayor complejidad):
1. **Filtrar**: aceptar solo subjects que estén en una allowlist de géneros conocidos (Fiction, Science Fiction, Fantasy, Mystery, etc.)
2. **Truncar**: ignorar subjects con más de N caracteres o que contengan paréntesis
3. **Mapear**: mapear subjects de OL a géneros normalizados (requiere mantenimiento)

Opción recomendada: filtrar por allowlist + truncar subjects largos.

### Verificación
`GET /books/harry-potter-and-the-philosophers-stone-1997` no debe mostrar géneros tipo "Wizards -- Juvenile fiction".

---

## Issue 5 — Test fixtures en la base de datos de producción

**Severidad:** Baja (elevada a Media el 2026-07-04: el sync nocturno funcional puebla la DB compartida y rompe 2 tests → init.sh en rojo)  
**Estado:** ✅ Resuelto (2026-07-05, rama fix/test-db-isolation) — DB backlogg_test en Neon, TEST_DATABASE_URL en .env y CI, conftest.py aislado con guardia de seguridad + TRUNCATE de sesión, 6 filas falsas borradas de prod (2 movies, 2 series, 1 book, 1 game). Reviewer: APPROVED

### Síntoma
Aparecen items en la DB local con datos de tests:
- `"Recommended Movie 2008"` con `poster_url: "https://image.tmdb.org/t/p/w500/rec.jpg"` (URL falsa)
- `"Dune 1965 search test"` (slug con sufijo de test)

### Causa
Tests que usan la DB de test real (`backlogg_test`) pero que en algún momento se ejecutaron contra la DB principal, o que usan fixtures que apuntan a la misma DB.

### Solución
1. Verificar que `TEST_DATABASE_URL` en `.env` apunta a `backlogg_test` (no a la misma DB que `DATABASE_URL`)
2. Limpiar los items falsos directamente en la DB:
   ```sql
   DELETE FROM movies WHERE slug = 'recommended-movie-2008';
   DELETE FROM movies WHERE slug LIKE '%-search-test%';
   ```
3. Revisar que los tests de integración no compartan sesión con la DB de producción

### Verificación
`GET /movies?limit=100&sort=date_asc` no debe mostrar items con slugs de test.

---

## Resumen de estado admin

Según `GET /admin/stats` (2026-06-21):

| Tipo    | Items en DB | Último sync        |
|---------|-------------|---------------------|
| movies  | 253         | 2026-06-21 14:17 UTC |
| series  | 241         | 2026-06-21 14:15 UTC |
| books   | 111         | 2026-06-21 14:17 UTC |
| games   | 112         | 2026-06-21 14:13 UTC |

El sync nocturno via GitHub Actions está configurado (`0 2 * * *`).

---

---

## Issue 6 — Personas duplicadas causan 500 en on-demand fallback

**Severidad:** Alta (causa 500)  
**Estado:** ✅ Resuelto (PR #37)  
**Descubierto:** al verificar Issue 1 en vivo

### Síntoma
`GET /movies/the-truman-show-1998` devuelve **500 Internal Server Error**:
```
IntegrityError: duplicate key value violates unique constraint "uq_external_id"
DETAIL: Key (source, external_id)=(TMDB, 350) already exists.
```

### Causa
En `_persist_movie_people` (y equivalentes de series/books), la deduplicación de personas se hace por **slug** (`upsert_person` busca `ON CONFLICT ON CONSTRAINT uq_person_slug`). Si el mismo actor TMDB aparece en dos películas con nombres ligeramente distintos, se crean dos registros `people` con distinto `id`. Al intentar enlazar el segundo registro al mismo TMDB ID, viola `uq_external_id` (que garantiza que cada TMDB ID externo apunte a un solo `person`).

### Solución
En `_persist_movie_people`, `_persist_series_people` y `_persist_book_authors`, antes de `upsert_person` consultar `external_ids` por `(source='TMDB', external_id=str(tmdb_person_id))` para obtener el `person_id` existente si lo hay. Solo crear/actualizar la persona si no hay registro previo en `external_ids`.

```python
# Pseudocódigo del lookup previo
existing = await db.execute(
    select(ExternalId).where(
        ExternalId.source == "TMDB",
        ExternalId.external_id == str(person_tmdb_id),
        ExternalId.item_type == "PERSON",
    )
)
ext = existing.scalar_one_or_none()
if ext:
    person = await people_repo.get_person_by_id(db, ext.item_id)
else:
    person = await people_repo.upsert_person(db, {...})
    await upsert_external_id(db, "PERSON", person.id, "TMDB", str(person_tmdb_id))
```

Alternativamente (fix más simple): en `upsert_external_id`, añadir un segundo ON CONFLICT para `uq_external_id` con DO NOTHING, evitando la excepción aunque deje el link al primer registro encontrado.

### Verificación
`GET /movies/the-truman-show-1998` debe devolver 200 con `credits[]` no vacío.

---

## Orden de ataque sugerido

1. ~~**Issue 1** (re-sync para poblar credits)~~ ✅ PR #37 + #39
2. ~~**Issue 6** (personas duplicadas → 500)~~ ✅ PR #37
3. ~~**Issue 3** (games on-demand)~~ ✅ PR #38
4. ~~**Issue 2** (movie slug+año)~~ ✅ PR #38
5. ~~**Issue 4** (géneros de libros)~~ ✅ PR #38
6. ~~**Issue 5** (test fixtures en DB)~~ ✅ fix/test-db-isolation
