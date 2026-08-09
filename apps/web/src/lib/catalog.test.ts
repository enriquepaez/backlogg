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
  bookListFixture,
  gameListFixture,
  movieListFixture,
  seriesListFixture,
  trendingFixture,
} from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const { getAllFeatured, getFeatured, getTrending } = await import(
  "./catalog"
);

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
