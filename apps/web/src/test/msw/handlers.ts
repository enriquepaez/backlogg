import { http, HttpResponse } from "msw";

import type { components } from "@backlogg/api-client";

type MovieOut = components["schemas"]["MovieOut"];
type MovieListOut = components["schemas"]["MovieListOut"];
type SeriesListOut = components["schemas"]["SeriesListOut"];
type BookListOut = components["schemas"]["BookListOut"];
type GameListOut = components["schemas"]["GameListOut"];
type TrendingOut = components["schemas"]["TrendingOut"];

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

/**
 * Minimal, reusable set of `/v1` handlers. Extend this array (or use
 * `server.use(...)` from `./server` for a one-off override in a single test)
 * as more of the API surface needs mocking in unit/integration tests.
 */
export const handlers = [
  http.get(`${MOCK_API_BASE_URL}/v1/movies`, () => {
    return HttpResponse.json(movieListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/movies/:slug`, ({ params }) => {
    if (params.slug === duneFixture.slug) {
      return HttpResponse.json(duneFixture);
    }
    return HttpResponse.json({ detail: "Movie not found" }, { status: 404 });
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/series`, () => {
    return HttpResponse.json(seriesListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/books`, () => {
    return HttpResponse.json(bookListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/games`, () => {
    return HttpResponse.json(gameListFixture);
  }),

  http.get(`${MOCK_API_BASE_URL}/v1/trending`, () => {
    return HttpResponse.json(trendingFixture);
  }),
];
