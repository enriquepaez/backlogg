// @vitest-environment node
//
// Exercises the public catalog helpers (FE-8: home landing) against the MSW
// mock server, same pattern as `src/test/msw/api-client.msw.test.ts`. The
// only wrinkle is that `getApiClient()` normally comes from
// `@/lib/auth/session`, which starts with `import "server-only"` — that
// resolves fine inside the Next.js bundler but not under plain Vitest (see
// `src/lib/catalog.ts`'s module doc), so it's mocked here to return a client
// bound to the MSW mock origin instead of ever loading the real module.
import { createApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  MOCK_API_BASE_URL,
  allGenresFixture,
  bookListFixture,
  chernobylFixture,
  duneBookFixture,
  duneFixture,
  gameListFixture,
  genreListFixture,
  hadesFixture,
  movieGenreFilteredFixture,
  movieListFixture,
  movieListPage2Fixture,
  seriesGenresFixture,
  seriesListFixture,
  similarBooksFixture,
  similarGamesFixture,
  similarMoviesFixture,
  similarSeriesFixture,
  trendingFixture,
  trendingMoviesOnlyFixture,
} from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const {
  getAllFeatured,
  getFeatured,
  getGenrePage,
  getGenres,
  getItemDetail,
  getSimilarItems,
  getTrending,
  getTrendingPage,
  isCatalogType,
  itemDetailCacheTag,
  listCatalog,
} = await import("./catalog");

describe("getTrending", () => {
  it("returns the trending results on success", async () => {
    expect(await getTrending()).toEqual(trendingFixture.results);
  });

  it("degrades to an empty array on a non-200 response", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/trending`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getTrending()).toEqual([]);
  });

  it("degrades to an empty array when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/trending`, () => HttpResponse.error()),
    );

    expect(await getTrending()).toEqual([]);
  });
});

describe("getFeatured", () => {
  it("returns movie items on success", async () => {
    expect(await getFeatured("movie")).toEqual(movieListFixture.items);
  });

  it("returns series items on success", async () => {
    expect(await getFeatured("series")).toEqual(seriesListFixture.items);
  });

  it("returns book items on success", async () => {
    expect(await getFeatured("book")).toEqual(bookListFixture.items);
  });

  it("returns game items on success", async () => {
    expect(await getFeatured("game")).toEqual(gameListFixture.items);
  });

  it("degrades to an empty array on a non-200 response", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/movies`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getFeatured("movie")).toEqual([]);
  });

  it("degrades to an empty array when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/games`, () => HttpResponse.error()),
    );

    expect(await getFeatured("game")).toEqual([]);
  });
});

describe("getAllFeatured", () => {
  it("fetches all four catalog types keyed by type", async () => {
    expect(await getAllFeatured()).toEqual({
      movie: movieListFixture.items,
      series: seriesListFixture.items,
      book: bookListFixture.items,
      game: gameListFixture.items,
    });
  });
});

describe("listCatalog", () => {
  it("returns the unfiltered page-1 list by default", async () => {
    expect(await listCatalog("movie")).toEqual({
      ok: true,
      ...movieListFixture,
    });
  });

  it("applies the genre filter", async () => {
    expect(await listCatalog("movie", { genre: "science-fiction" })).toEqual({
      ok: true,
      ...movieGenreFilteredFixture,
    });
  });

  it("applies the page param", async () => {
    expect(await listCatalog("movie", { page: 2 })).toEqual({
      ok: true,
      ...movieListPage2Fixture,
    });
  });

  it("returns ok: false on a non-200 response — distinct from an empty result", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/series`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await listCatalog("series")).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/books`, () => HttpResponse.error()),
    );

    expect(await listCatalog("book")).toEqual({ ok: false });
  });

  it("forwards search/date-range/rating-range filters (feature 50) to the request query string", async () => {
    let requestedUrl = "";
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/movies`, ({ request }) => {
        requestedUrl = request.url;
        return HttpResponse.json(movieListFixture);
      }),
    );

    await listCatalog("movie", {
      search: "dune",
      dateFrom: "2020-01-01",
      dateTo: "2021-12-31",
      ratingInternalMin: 3,
      ratingInternalMax: 5,
      ratingExternalMin: 6.5,
      ratingExternalMax: 9,
    });

    const params = new URL(requestedUrl).searchParams;
    expect(params.get("search")).toBe("dune");
    expect(params.get("date_from")).toBe("2020-01-01");
    expect(params.get("date_to")).toBe("2021-12-31");
    expect(params.get("rating_internal_min")).toBe("3");
    expect(params.get("rating_internal_max")).toBe("5");
    expect(params.get("rating_external_min")).toBe("6.5");
    expect(params.get("rating_external_max")).toBe("9");
  });
});

describe("getGenres", () => {
  it("returns genre options on success", async () => {
    expect(await getGenres("movie")).toEqual(
      genreListFixture.genres.map((genre) => ({
        name: genre.name,
        slug: genre.slug,
        count: genre.count,
      })),
    );
  });

  it("degrades to an empty array on a non-200 response", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/genres`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getGenres("movie")).toEqual([]);
  });

  it("degrades to an empty array when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/genres`, () => HttpResponse.error()),
    );

    expect(await getGenres("movie")).toEqual([]);
  });
});

describe("getGenrePage", () => {
  it("returns all genres (with item_type) when no type is given", async () => {
    expect(await getGenrePage()).toEqual({ ok: true, genres: allGenresFixture.genres });
  });

  it("applies the type filter", async () => {
    expect(await getGenrePage("series")).toEqual({ ok: true, genres: seriesGenresFixture.genres });
  });

  it("returns ok: false on a non-200 response — distinct from an empty result", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/genres`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getGenrePage()).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/genres`, () => HttpResponse.error()),
    );

    expect(await getGenrePage()).toEqual({ ok: false });
  });
});

describe("getTrendingPage", () => {
  it("returns the mixed movie+series results by default", async () => {
    expect(await getTrendingPage()).toEqual({ ok: true, results: trendingFixture.results });
  });

  it("applies the type filter", async () => {
    expect(await getTrendingPage({ type: "movie" })).toEqual({
      ok: true,
      results: trendingMoviesOnlyFixture.results,
    });
  });

  it("returns ok: false on a non-200 response — distinct from an empty result", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/trending`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getTrendingPage()).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/trending`, () => HttpResponse.error()),
    );

    expect(await getTrendingPage()).toEqual({ ok: false });
  });
});

describe("getItemDetail", () => {
  it("returns the movie on success", async () => {
    expect(await getItemDetail("movie", duneFixture.slug)).toEqual({
      status: "ok",
      item: duneFixture,
    });
  });

  it("returns the series on success", async () => {
    expect(await getItemDetail("series", chernobylFixture.slug)).toEqual({
      status: "ok",
      item: chernobylFixture,
    });
  });

  it("returns the book on success", async () => {
    expect(await getItemDetail("book", duneBookFixture.slug)).toEqual({
      status: "ok",
      item: duneBookFixture,
    });
  });

  it("returns the game on success", async () => {
    expect(await getItemDetail("game", hadesFixture.slug)).toEqual({
      status: "ok",
      item: hadesFixture,
    });
  });

  it("reports status: not-found on a real backend 404 (unknown slug)", async () => {
    expect(await getItemDetail("movie", "does-not-exist")).toEqual({
      status: "not-found",
    });
  });

  it("reports status: error (not not-found) on a non-200/404 response — a transient failure must not look like a permanent 404", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/movies/:slug`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getItemDetail("movie", duneFixture.slug)).toEqual({ status: "error" });
  });

  it("reports status: error when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/movies/:slug`, () => HttpResponse.error()),
    );

    expect(await getItemDetail("movie", duneFixture.slug)).toEqual({ status: "error" });
  });
});

describe("itemDetailCacheTag", () => {
  // Bugfix (post-FE-18 QA): reproduced live against the real backend + `next
  // dev` — the item detail page's "Backlogg rating" (both `ItemHero`'s chip
  // and `RatingWidget`'s own `initialRatingInternal` seed, both sourced from
  // this same `getItemDetail` fetch) stayed stuck at "No ratings yet" after a
  // reload, even though `GET /v1/{type}/{slug}` already returned the fresh
  // `rating_internal` on the wire — the fetch-level ISR cache
  // (`ITEM_REVALIDATE_SECONDS`, 1h) never got invalidated by the caller's own
  // rating change. `PUT`/`DELETE /api/{type}/{slug}/rating` now call
  // `revalidateTag(itemDetailCacheTag(type, slug))` on success
  // (`route.test.ts` asserts that call); this only pins down the tag's
  // shape — one per (type, slug), locale-independent, matching the fetch it
  // tags in `getItemDetail` above.
  it("is stable and unique per (type, slug), independent of locale", () => {
    expect(itemDetailCacheTag("movie", "dune-2021")).toBe("item-detail:movie:dune-2021");
    expect(itemDetailCacheTag("movie", "dune-2021")).toBe(itemDetailCacheTag("movie", "dune-2021"));
    expect(itemDetailCacheTag("series", "dune-2021")).not.toBe(itemDetailCacheTag("movie", "dune-2021"));
    expect(itemDetailCacheTag("movie", "dune-1984")).not.toBe(itemDetailCacheTag("movie", "dune-2021"));
  });
});

describe("getSimilarItems", () => {
  it("returns similar movies on success", async () => {
    expect(await getSimilarItems("movie", duneFixture.slug)).toEqual(
      similarMoviesFixture.results,
    );
  });

  it("returns similar series on success", async () => {
    expect(await getSimilarItems("series", chernobylFixture.slug)).toEqual(
      similarSeriesFixture.results,
    );
  });

  it("returns similar books on success", async () => {
    expect(await getSimilarItems("book", duneBookFixture.slug)).toEqual(
      similarBooksFixture.results,
    );
  });

  it("returns similar games on success", async () => {
    expect(await getSimilarItems("game", hadesFixture.slug)).toEqual(
      similarGamesFixture.results,
    );
  });

  it("degrades to an empty array on a non-200 response", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/movies/:slug/similar`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getSimilarItems("movie", duneFixture.slug)).toEqual([]);
  });

  it("degrades to an empty array when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/series/:slug/similar`, () => HttpResponse.error()),
    );

    expect(await getSimilarItems("series", chernobylFixture.slug)).toEqual([]);
  });

  it("degrades to an empty array on a non-200 response for books", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/books/:slug/similar`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getSimilarItems("book", duneBookFixture.slug)).toEqual([]);
  });

  it("degrades to an empty array when the network fails for games", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/games/:slug/similar`, () => HttpResponse.error()),
    );

    expect(await getSimilarItems("game", hadesFixture.slug)).toEqual([]);
  });
});

describe("isCatalogType", () => {
  it("accepts the four known catalog types", () => {
    expect(isCatalogType("movie")).toBe(true);
    expect(isCatalogType("series")).toBe(true);
    expect(isCatalogType("book")).toBe(true);
    expect(isCatalogType("game")).toBe(true);
  });

  it("rejects anything else", () => {
    expect(isCatalogType("movies")).toBe(false);
    expect(isCatalogType("")).toBe(false);
    expect(isCatalogType("MOVIE")).toBe(false);
  });
});
