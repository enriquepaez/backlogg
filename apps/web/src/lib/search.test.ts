// @vitest-environment node
//
// Exercises `searchCatalog` (FE-11 global search) against the MSW mock
// server, same pattern as `src/lib/catalog.test.ts` — `@/lib/auth/session`
// is mocked to a client bound to the mock origin so this can run under
// plain Vitest without pulling in `server-only`.
import { createApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { MOCK_API_BASE_URL, searchEmptyFixture, searchResultsFixture } from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const { searchCatalog, toCatalogType } = await import("./search");

describe("searchCatalog", () => {
  it("returns ok with the results on a real hit", async () => {
    expect(await searchCatalog("dune")).toEqual({ status: "ok", ...searchResultsFixture });
  });

  it("returns ok with an empty results array — a real 'no matches' state, not an error", async () => {
    expect(await searchCatalog("no-results")).toEqual({ status: "ok", ...searchEmptyFixture });
  });

  it("returns status: invalid on a 422 (empty q)", async () => {
    expect(await searchCatalog("")).toEqual({ status: "invalid" });
  });

  it("returns status: rate-limited with the parsed Retry-After on a 429", async () => {
    expect(await searchCatalog("rate-limited")).toEqual({
      status: "rate-limited",
      retryAfterSeconds: 30,
    });
  });

  it("returns retryAfterSeconds: null when the 429 has no Retry-After header", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/search`, () =>
        HttpResponse.json({ detail: "Too Many Requests" }, { status: 429 }),
      ),
    );

    expect(await searchCatalog("dune")).toEqual({ status: "rate-limited", retryAfterSeconds: null });
  });

  it("returns status: error on an unexpected non-200 response", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/search`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await searchCatalog("dune")).toEqual({ status: "error" });
  });

  it("returns status: error when the network fails", async () => {
    server.use(http.get(`${MOCK_API_BASE_URL}/v1/search`, () => HttpResponse.error()));

    expect(await searchCatalog("dune")).toEqual({ status: "error" });
  });
});

describe("toCatalogType", () => {
  it("lowercases known item types", () => {
    expect(toCatalogType("MOVIE")).toBe("movie");
    expect(toCatalogType("SERIES")).toBe("series");
    expect(toCatalogType("BOOK")).toBe("book");
    expect(toCatalogType("GAME")).toBe("game");
  });

  it("returns undefined for an unrecognized item type", () => {
    expect(toCatalogType("PERSON")).toBeUndefined();
  });
});
