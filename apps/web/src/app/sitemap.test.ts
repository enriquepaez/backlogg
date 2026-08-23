// @vitest-environment node
//
// Exercises `sitemap.ts` (FE-46) against the MSW mock server, same pattern as
// `src/lib/catalog.test.ts`: `@/lib/auth/session` is mocked so `getApiClient()`
// resolves to a client bound to the mock origin instead of pulling in
// `server-only`/`API_INTERNAL_URL` under plain Vitest. `@/lib/env` is mocked
// too so `SITE_URL` is deterministic regardless of the host machine's env.
import { createApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  MOCK_API_BASE_URL,
  bookListFixture,
  duneFixture,
  gameListFixture,
  movieListFixture,
  movieListPage2Fixture,
  seriesListFixture,
} from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

vi.mock("@/lib/env", () => ({
  env: { SITE_URL: "https://backlogg.example" },
}));

const { default: sitemap } = await import("./sitemap");

describe("sitemap", () => {
  it("includes one entry per catalog type on the happy path, with hreflang alternates for both locales", async () => {
    const entries = await sitemap();

    const movieEntry = entries.find(
      (entry) => entry.url === `https://backlogg.example/en/movie/${duneFixture.slug}`,
    );
    expect(movieEntry).toBeDefined();
    expect(movieEntry?.alternates?.languages).toEqual({
      en: `https://backlogg.example/en/movie/${duneFixture.slug}`,
      es: `https://backlogg.example/es/movie/${duneFixture.slug}`,
    });

    expect(entries).toContainEqual(
      expect.objectContaining({
        url: `https://backlogg.example/en/series/${seriesListFixture.items[0].slug}`,
      }),
    );
    expect(entries).toContainEqual(
      expect.objectContaining({
        url: `https://backlogg.example/en/book/${bookListFixture.items[0].slug}`,
      }),
    );
    expect(entries).toContainEqual(
      expect.objectContaining({
        url: `https://backlogg.example/en/game/${gameListFixture.items[0].slug}`,
      }),
    );

    // Exactly one entry per fixture item across the four types.
    expect(entries).toHaveLength(4);
  });

  it("walks every page of a paginated type until `total` is exhausted", async () => {
    // Two-page movies catalog (`total: 2`, one item per page) — distinct from
    // `movieListFixture`/`movieListPage2Fixture` (FE-9's own pagination
    // fixtures, whose `total`s don't agree with each other) so `total` stays
    // internally consistent across both pages here.
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/movies`, ({ request }) => {
        const url = new URL(request.url);
        const page = url.searchParams.get("page");
        if (page === "2") {
          return HttpResponse.json({
            items: [movieListPage2Fixture.items[0]],
            total: 2,
            page: 2,
            limit: 100,
          });
        }
        return HttpResponse.json({
          items: [movieListFixture.items[0]],
          total: 2,
          page: 1,
          limit: 100,
        });
      }),
    );

    const entries = await sitemap();
    const movieUrls = entries
      .filter((entry) => entry.url.includes("/movie/"))
      .map((entry) => entry.url);

    expect(movieUrls).toContain(`https://backlogg.example/en/movie/${movieListFixture.items[0].slug}`);
    expect(movieUrls).toContain(
      `https://backlogg.example/en/movie/${movieListPage2Fixture.items[0].slug}`,
    );
  });

  it("degrades to no entries for a type whose endpoint fails, without dropping the others", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/games`, () => HttpResponse.error()),
    );

    const entries = await sitemap();

    expect(entries.some((entry) => entry.url.includes("/game/"))).toBe(false);
    expect(entries.some((entry) => entry.url.includes("/movie/"))).toBe(true);
  });
});
