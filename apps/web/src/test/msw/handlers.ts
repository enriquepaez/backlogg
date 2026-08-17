import { http, HttpResponse } from "msw";

import type { components } from "@backlogg/api-client";

type MovieOut = components["schemas"]["MovieOut"];
type MovieListOut = components["schemas"]["MovieListOut"];
type SeriesOut = components["schemas"]["SeriesOut"];
type SeriesListOut = components["schemas"]["SeriesListOut"];
type BookOut = components["schemas"]["BookOut"];
type BookListOut = components["schemas"]["BookListOut"];
type GameOut = components["schemas"]["GameOut"];
type GameListOut = components["schemas"]["GameListOut"];
type TrendingOut = components["schemas"]["TrendingOut"];
type GenreListOut = components["schemas"]["GenreListOut"];
type SimilarMoviesOut = components["schemas"]["SimilarMoviesOut"];
type SimilarSeriesListOut = components["schemas"]["SimilarSeriesListOut"];
type SimilarBooksOut = components["schemas"]["SimilarBooksOut"];
type SimilarGameListOut = components["schemas"]["SimilarGameListOut"];
type SearchResponse = components["schemas"]["SearchResponse"];

/**
 * Base URL these handlers are registered against. Tests build their
 * `createApiClient` (or `fetch`) calls with this same origin so MSW can
 * intercept them — it never talks to a real backend.
 */
export const MOCK_API_BASE_URL = "http://backlogg-test.local";

/**
 * A single fixture reused for both the list and detail handlers, mirroring
 * the shapes documented in `packages/api-client/openapi.json`'s own
 * `MovieOut`/`MovieListOut` examples (movies domain, chosen as the smallest
 * representative slice of `/v1`).
 */
export const duneFixture: MovieOut = {
  id: 1,
  title: "Dune",
  original_title: "Dune",
  slug: "dune-2021",
  overview: "Paul Atreides unites with the Fremen of Arrakis.",
  release_date: "2021-10-22",
  runtime: 155,
  original_language: "en",
  poster_url: "https://image.tmdb.org/t/p/w500/dune.jpg",
  backdrop_url: "https://image.tmdb.org/t/p/w780/dune-bd.jpg",
  budget: 165000000,
  revenue: 401800000,
  status: "Released",
  rating_external: 7.8,
  rating_count_external: 9231,
  rating_internal: 4.2,
  rating_count_internal: 87,
  genres: [{ id: 3, name: "Science Fiction", slug: "science-fiction" }],
  credits: [
    {
      role: "cast",
      person_name: "Timothée Chalamet",
      person_slug: "timothee-chalamet",
      character_name: "Paul Atreides",
      profile_url: "https://image.tmdb.org/t/p/w185/tc.jpg",
      billing_order: 0,
    },
  ],
  viewer_status: null,
};

export const movieListFixture: MovieListOut = {
  items: [
    {
      id: duneFixture.id,
      title: duneFixture.title,
      slug: duneFixture.slug,
      poster_url: duneFixture.poster_url,
      release_date: duneFixture.release_date,
      rating_external: duneFixture.rating_external,
      genres: duneFixture.genres.map((genre) => genre.slug),
    },
  ],
  total: 1,
  page: 1,
  limit: 20,
};

/**
 * List fixtures for the other three catalog types (FE-8 home landing:
 * "featured" sections). `MovieListItemOut` / `SeriesListItemOut` /
 * `BookListItemOut` / `GameListItemOut` all share the exact same shape, so
 * these mirror `movieListFixture.items[0]` with a type-appropriate title.
 */
export const seriesListFixture: SeriesListOut = {
  items: [
    {
      id: 2,
      title: "Chernobyl",
      slug: "chernobyl",
      poster_url: "https://image.tmdb.org/t/p/w500/chernobyl.jpg",
      release_date: "2019-05-06",
      rating_external: 8.5,
      genres: ["drama"],
    },
  ],
  total: 1,
  page: 1,
  limit: 20,
};

export const bookListFixture: BookListOut = {
  items: [
    {
      id: 3,
      title: "Dune",
      slug: "OL893415W",
      poster_url: "https://covers.openlibrary.org/b/id/12-L.jpg",
      release_date: "1965-08-01",
      rating_external: 4.3,
      genres: ["science-fiction"],
    },
  ],
  total: 1,
  page: 1,
  limit: 20,
};

export const gameListFixture: GameListOut = {
  items: [
    {
      id: 4,
      title: "Hades",
      slug: "hades",
      poster_url: "https://images.igdb.com/igdb/image/upload/t_cover_big/hades.jpg",
      release_date: "2020-09-17",
      rating_external: 9.1,
      genres: ["roguelike"],
    },
  ],
  total: 1,
  page: 1,
  limit: 20,
};

/**
 * Detail fixtures for series/book/game (FE-10 item detail), mirroring
 * `duneFixture` (movie) above — one representative item per type, matching
 * the response fields documented in `docs/api.md`.
 */
export const chernobylFixture: SeriesOut = {
  id: 2,
  title: "Chernobyl",
  original_title: "Chernobyl",
  slug: "chernobyl",
  overview: "In April 1986, an explosion at the Chernobyl nuclear power plant.",
  first_air_date: "2019-05-06",
  last_air_date: "2019-06-03",
  number_of_seasons: 1,
  number_of_episodes: 5,
  status: "Ended",
  original_language: "en",
  poster_url: "https://image.tmdb.org/t/p/w500/chernobyl.jpg",
  backdrop_url: "https://image.tmdb.org/t/p/w780/chernobyl-bd.jpg",
  rating_external: 8.5,
  rating_count_external: 3200,
  rating_internal: null,
  rating_count_internal: 0,
  genres: [{ id: 5, name: "Drama", slug: "drama" }],
  credits: [
    {
      role: "cast",
      person_name: "Jared Harris",
      person_slug: "jared-harris",
      character_name: "Valery Legasov",
      profile_url: null,
      billing_order: 0,
    },
  ],
  viewer_status: null,
};

export const duneBookFixture: BookOut = {
  id: 3,
  title: "Dune",
  original_title: "Dune",
  slug: "OL893415W",
  overview: "Set on the desert planet Arrakis.",
  first_publish_date: "1965-08-01",
  original_language: "en",
  poster_url: "https://covers.openlibrary.org/b/id/12-L.jpg",
  rating_external: 4.3,
  rating_count_external: 500,
  rating_internal: null,
  rating_count_internal: 0,
  genres: [{ id: 3, name: "Science Fiction", slug: "science-fiction" }],
  credits: [
    {
      role: "AUTHOR",
      person_name: "Frank Herbert",
      person_slug: "frank-herbert",
      character_name: null,
      profile_url: null,
      billing_order: null,
    },
  ],
  viewer_status: null,
};

export const hadesFixture: GameOut = {
  id: 4,
  title: "Hades",
  original_title: "Hades",
  slug: "hades",
  overview: "Defy the god of the dead as you hack and slash out of the Underworld.",
  release_date: "2020-09-17",
  game_type: "main_game",
  original_language: "en",
  poster_url: "https://images.igdb.com/igdb/image/upload/t_cover_big/hades.jpg",
  backdrop_url: "https://images.igdb.com/igdb/image/upload/t_screenshot_big/hades-bd.jpg",
  rating_external: 9.1,
  rating_count_external: 1500,
  rating_internal: null,
  rating_count_internal: 0,
  genres: [{ id: 6, name: "Roguelike", slug: "roguelike" }],
  platforms: [{ id: 1, name: "PC", slug: "pc" }],
  credits: [
    {
      role: "developer",
      person_name: "Supergiant Games",
      person_slug: "supergiant-games",
      character_name: null,
      profile_url: null,
      billing_order: 0,
    },
  ],
  viewer_status: null,
};

/** `GET /v1/movies/{slug}/similar` (FE-10). */
export const similarMoviesFixture: SimilarMoviesOut = {
  results: [
    {
      title: "Arrival",
      slug: "arrival-2016",
      poster_url: "https://image.tmdb.org/t/p/w500/arrival.jpg",
      release_date: "2016-11-11",
      rating_external: 7.9,
    },
  ],
};

/** `GET /v1/series/{slug}/similar` (FE-10). */
export const similarSeriesFixture: SimilarSeriesListOut = {
  results: [
    {
      title: "The Last of Us",
      slug: "the-last-of-us",
      poster_url: "https://image.tmdb.org/t/p/w500/tlou.jpg",
      release_date: "2023-01-15",
      rating_external: 8.7,
    },
  ],
};

/** `GET /v1/books/{slug}/similar` (FE-32). */
export const similarBooksFixture: SimilarBooksOut = {
  results: [
    {
      title: "Dune Messiah",
      slug: "OL893416W",
      poster_url: "https://covers.openlibrary.org/b/id/13-L.jpg",
      release_date: "1969-10-01",
      rating_external: 4.1,
    },
  ],
};

/** `GET /v1/games/{slug}/similar` (FE-32). */
export const similarGamesFixture: SimilarGameListOut = {
  results: [
    {
      title: "Bastion",
      slug: "bastion",
      poster_url: "https://images.igdb.com/igdb/image/upload/t_cover_big/bastion.jpg",
      release_date: "2011-07-20",
      rating_external: 8.7,
    },
  ],
};

/**
 * Second page of the movies list (FE-9 browse: pagination). `total: 30` with
 * `limit: 24` (the browse page's fixed page size, see `BROWSE_PAGE_SIZE` in
 * `src/lib/catalog.ts`) puts this at page 2 of 2.
 */
export const movieListPage2Fixture: MovieListOut = {
  items: [
    {
      id: 5,
      title: "Arrival",
      slug: "arrival-2016",
      poster_url: "https://image.tmdb.org/t/p/w500/arrival.jpg",
      release_date: "2016-11-11",
      rating_external: 7.9,
      genres: [duneFixture.genres[0].slug],
    },
  ],
  total: 30,
  page: 2,
  limit: 24,
};

/** Movies list filtered to a single genre (FE-9 browse: genre filter). */
export const movieGenreFilteredFixture: MovieListOut = {
  items: [movieListFixture.items[0]],
  total: 1,
  page: 1,
  limit: 24,
};

/** Genre options for the movies browse filter (FE-9), `GET /v1/genres?type=movie`. */
export const genreListFixture: GenreListOut = {
  genres: [
    { name: "Science Fiction", slug: "science-fiction", item_type: "movie", count: 42 },
    { name: "Adventure", slug: "adventure", item_type: "movie", count: 17 },
  ],
};

/**
 * All genres across all four types (FE-12 `/genres` browse page),
 * `GET /v1/genres` with no `type` filter. Includes the same movie genres as
 * {@link genreListFixture} plus one genre for each of the other three types.
 */
export const allGenresFixture: GenreListOut = {
  genres: [
    ...genreListFixture.genres,
    { name: "Drama", slug: "drama", item_type: "series", count: 8 },
    { name: "Science Fiction", slug: "science-fiction", item_type: "book", count: 3 },
    { name: "Roguelike", slug: "roguelike", item_type: "game", count: 5 },
  ],
};

/** Genres filtered to `type=series` (FE-12 `/genres?type=series`). */
export const seriesGenresFixture: GenreListOut = {
  genres: [{ name: "Drama", slug: "drama", item_type: "series", count: 8 }],
};

export const trendingFixture: TrendingOut = {
  results: [
    {
      item_type: "MOVIE",
      title: duneFixture.title,
      slug: duneFixture.slug,
      poster_url: duneFixture.poster_url,
      release_date: duneFixture.release_date,
      rating_external: duneFixture.rating_external,
    },
    {
      item_type: "SERIES",
      title: seriesListFixture.items[0].title,
      slug: seriesListFixture.items[0].slug,
      poster_url: seriesListFixture.items[0].poster_url,
      release_date: seriesListFixture.items[0].release_date,
      rating_external: seriesListFixture.items[0].rating_external,
    },
  ],
};

/** Trending filtered to `type=movie` (FE-12 `/trending?type=movie`). */
export const trendingMoviesOnlyFixture: TrendingOut = {
  results: [trendingFixture.results[0]],
};

/** `GET /v1/search` on a real hit (FE-11 global search). */
export const searchResultsFixture: SearchResponse = {
  results: [
    {
      id: duneFixture.id,
      item_type: "MOVIE",
      slug: duneFixture.slug,
      title: duneFixture.title,
      overview: duneFixture.overview,
      poster_url: duneFixture.poster_url,
      release_date: duneFixture.release_date,
      rating_external: duneFixture.rating_external,
    },
  ],
  total: 1,
  page: 1,
  limit: 24,
};

/** `GET /v1/search` when the query matches nothing (FE-11: empty-results state). */
export const searchEmptyFixture: SearchResponse = {
  results: [],
  total: 0,
  page: 1,
  limit: 24,
};

/**
 * Minimal, reusable set of `/v1` handlers. Extend this array (or use
 * `server.use(...)` from `./server` for a one-off override in a single test)
 * as more of the API surface needs mocking in unit/integration tests.
 */
export const handlers = [
  // Respects `genre`/`page` (FE-9 browse: filter + pagination) so tests can
  // exercise those states; falls back to the page-1/unfiltered fixture
  // (also what FE-8's `getFeatured` — sort+limit only, no genre/page — hits).
  http.get(`${MOCK_API_BASE_URL}/v1/movies`, ({ request }) => {
    const url = new URL(request.url);
    const genre = url.searchParams.get("genre");
    const page = url.searchParams.get("page");

    if (genre === "science-fiction") {
      return HttpResponse.json(movieGenreFilteredFixture);
    }
    if (page === "2") {
      return HttpResponse.json(movieListPage2Fixture);
    }
    return HttpResponse.json(movieListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/genres`, ({ request }) => {
    const url = new URL(request.url);
    const type = url.searchParams.get("type");

    // No `type` (FE-12 `/genres`): all four types mixed together.
    if (!type) {
      return HttpResponse.json(allGenresFixture);
    }
    if (type === "series") {
      return HttpResponse.json(seriesGenresFixture);
    }
    if (type !== "movie") {
      return HttpResponse.json({ genres: [] } satisfies GenreListOut);
    }
    return HttpResponse.json(genreListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/movies/:slug`, ({ params }) => {
    if (params.slug === duneFixture.slug) {
      return HttpResponse.json(duneFixture);
    }
    return HttpResponse.json({ detail: "Movie not found" }, { status: 404 });
  }),

  // FE-10 item detail: similar movies. Registered separately from
  // `/v1/movies/:slug` above — msw's `:slug` param matches exactly one path
  // segment, so it never intercepts the extra `/similar` segment.
  http.get(`${MOCK_API_BASE_URL}/v1/movies/:slug/similar`, ({ params }) => {
    if (params.slug === duneFixture.slug) {
      return HttpResponse.json(similarMoviesFixture);
    }
    return HttpResponse.json({ detail: "Movie not found" }, { status: 404 });
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/series`, () => {
    return HttpResponse.json(seriesListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/series/:slug`, ({ params }) => {
    if (params.slug === chernobylFixture.slug) {
      return HttpResponse.json(chernobylFixture);
    }
    return HttpResponse.json({ detail: "Series not found" }, { status: 404 });
  }),

  // FE-10 item detail: similar series.
  http.get(`${MOCK_API_BASE_URL}/v1/series/:slug/similar`, ({ params }) => {
    if (params.slug === chernobylFixture.slug) {
      return HttpResponse.json(similarSeriesFixture);
    }
    return HttpResponse.json({ detail: "Series not found" }, { status: 404 });
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/books`, () => {
    return HttpResponse.json(bookListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/books/:slug`, ({ params }) => {
    if (params.slug === duneBookFixture.slug) {
      return HttpResponse.json(duneBookFixture);
    }
    return HttpResponse.json({ detail: "Book not found" }, { status: 404 });
  }),

  // FE-32 item detail: similar books.
  http.get(`${MOCK_API_BASE_URL}/v1/books/:slug/similar`, ({ params }) => {
    if (params.slug === duneBookFixture.slug) {
      return HttpResponse.json(similarBooksFixture);
    }
    return HttpResponse.json({ detail: "Book not found" }, { status: 404 });
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/games`, () => {
    return HttpResponse.json(gameListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/games/:slug`, ({ params }) => {
    if (params.slug === hadesFixture.slug) {
      return HttpResponse.json(hadesFixture);
    }
    return HttpResponse.json({ detail: "Game not found" }, { status: 404 });
  }),

  // FE-32 item detail: similar games.
  http.get(`${MOCK_API_BASE_URL}/v1/games/:slug/similar`, ({ params }) => {
    if (params.slug === hadesFixture.slug) {
      return HttpResponse.json(similarGamesFixture);
    }
    return HttpResponse.json({ detail: "Game not found" }, { status: 404 });
  }),

  // Respects `type` (FE-12 `/trending?type=`) so tests can exercise the
  // filtered state; ignores `period` (the fixture doesn't vary by period).
  http.get(`${MOCK_API_BASE_URL}/v1/trending`, ({ request }) => {
    const url = new URL(request.url);
    const type = url.searchParams.get("type");

    if (type === "movie") {
      return HttpResponse.json(trendingMoviesOnlyFixture);
    }
    return HttpResponse.json(trendingFixture);
  }),

  // FE-11 global search, re-scoped by `browse_search_filters` Fase 1
  // (backend): `q` is optional — absent is a valid filters-only search, but
  // an explicit `q=""` still 422s (`Field(default=None, min_length=1)`,
  // mirrored here), same as the real backend. `date_from`/`date_to`/
  // `rating_external_min`/`rating_external_max` are combinable with `q` and
  // 422 on an inverted range, mirroring the backend's own cross-field
  // validation. `no-results`/`rate-limited` are magic `q` values a test can
  // opt into instead of overriding this handler with `server.use(...)` every
  // time.
  http.get(`${MOCK_API_BASE_URL}/v1/search`, ({ request }) => {
    const url = new URL(request.url);
    const q = url.searchParams.get("q");
    const dateFrom = url.searchParams.get("date_from");
    const dateTo = url.searchParams.get("date_to");
    const ratingExternalMin = url.searchParams.get("rating_external_min");
    const ratingExternalMax = url.searchParams.get("rating_external_max");

    if (q === "") {
      return HttpResponse.json(
        {
          detail: [
            { loc: ["query", "q"], msg: "String should have at least 1 character", type: "string_too_short" },
          ],
        },
        { status: 422 },
      );
    }
    if (dateFrom && dateTo && dateFrom > dateTo) {
      return HttpResponse.json(
        { detail: [{ loc: ["query", "date_to"], msg: "date_from must be <= date_to", type: "value_error" }] },
        { status: 422 },
      );
    }
    if (
      ratingExternalMin !== null &&
      ratingExternalMax !== null &&
      Number(ratingExternalMin) > Number(ratingExternalMax)
    ) {
      return HttpResponse.json(
        {
          detail: [
            {
              loc: ["query", "rating_external_max"],
              msg: "rating_external_min must be <= rating_external_max",
              type: "value_error",
            },
          ],
        },
        { status: 422 },
      );
    }
    if (q === "no-results") {
      return HttpResponse.json(searchEmptyFixture);
    }
    if (q === "rate-limited") {
      return new HttpResponse(JSON.stringify({ detail: "Too Many Requests" }), {
        status: 429,
        headers: { "Content-Type": "application/json", "Retry-After": "30" },
      });
    }
    return HttpResponse.json(searchResultsFixture);
  }),
];
