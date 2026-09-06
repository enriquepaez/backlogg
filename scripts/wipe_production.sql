-- Vaciado completo de la base antes de la siembra desde cero.
--
-- Decisión del usuario (2026-09-06): base limpia — se borra TODO, catálogo y
-- cuentas. Producción no tiene datos reales, solo de prueba.
--
-- Por qué en un solo golpe (hallazgo L5 del review de los issues #23/#25):
-- si quedan filas en external_ids sin su ítem, con el issue #25 arreglado los
-- seed_targets vuelven a `pending` — visible, que es mejor que antes — pero el
-- id externo queda bloqueado hasta que se borre la fila. Truncar por partes
-- reintroduce exactamente el problema que la siembra limpia venía a evitar.
--
-- alembic_version NO se toca: el esquema se conserva, solo se vacían los datos.
--
-- USO (revisar antes de ejecutar):
--   psql "$DATABASE_URL" -f scripts/wipe_production.sql
--
-- ⚠️ IRREVERSIBLE. Comprobar dos veces contra qué base apunta $DATABASE_URL.

BEGIN;

TRUNCATE TABLE
    -- Catálogo
    movies, series, books, games,
    movie_genres, series_genres, book_genres, game_genres,
    movie_genres_join, series_genres_join, book_genres_join, game_genres_join,
    game_platforms, game_platforms_join,
    -- Personas, compañías y créditos
    people, companies, credits, company_credits,
    -- Identidad externa y estado de siembra/sync
    external_ids, seed_targets, sync_cursors,
    -- Cuentas y todo lo que cuelga de ellas
    users, account_tokens, refresh_tokens,
    user_ratings, review_likes, review_reports,
    library_entries, follows, activity_events, notifications,
    admin_actions
RESTART IDENTITY CASCADE;

COMMIT;

-- Comprobación posterior (debe devolver 0 en todas):
--   SELECT 'movies', count(*) FROM movies
--   UNION ALL SELECT 'series', count(*) FROM series
--   UNION ALL SELECT 'books', count(*) FROM books
--   UNION ALL SELECT 'games', count(*) FROM games
--   UNION ALL SELECT 'external_ids', count(*) FROM external_ids
--   UNION ALL SELECT 'seed_targets', count(*) FROM seed_targets
--   UNION ALL SELECT 'credits', count(*) FROM credits
--   UNION ALL SELECT 'people', count(*) FROM people
--   UNION ALL SELECT 'users', count(*) FROM users;
