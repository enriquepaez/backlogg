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

  it("omits the q param when the query is empty — a valid filters-only search, not a 422", async () => {
    let requestedUrl = "";
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/search`, ({ request }) => {
        requestedUrl = request.url;
        return HttpResponse.json(searchResultsFixture);
      }),
    );

    expect(await searchCatalog("")).toEqual({ status: "ok", ...searchResultsFixture });
    expect(new URL(requestedUrl).searchParams.has("q")).toBe(false);
  });

  it("omits the q param when the query is whitespace-only, even with filters active", async () => {
    let requestedUrl = "";
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/search`, ({ request }) => {
        requestedUrl = request.url;
        return HttpResponse.json(searchResultsFixture);
      }),
    );

    expect(await searchCatalog("   ", { dateFrom: "2020-01-01" })).toEqual({
      status: "ok",
      ...searchResultsFixture,
    });
    const params = new URL(requestedUrl).searchParams;
    expect(params.has("q")).toBe(false);
    expect(params.get("date_from")).toBe("2020-01-01");
  });

  it("forwards date-range and external-rating-range filters to the request query string", async () => {
    let requestedUrl = "";
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/search`, ({ request }) => {
        requestedUrl = request.url;
        return HttpResponse.json(searchResultsFixture);
      }),
    );

    await searchCatalog("dune", {
      dateFrom: "2020-01-01",
      dateTo: "2021-12-31",
      ratingExternalMin: 6.5,
      ratingExternalMax: 9,
    });

    const params = new URL(requestedUrl).searchParams;
    expect(params.get("q")).toBe("dune");
    expect(params.get("date_from")).toBe("2020-01-01");
    expect(params.get("date_to")).toBe("2021-12-31");
    expect(params.get("rating_external_min")).toBe("6.5");
    expect(params.get("rating_external_max")).toBe("9");
  });

  it("returns status: invalid on a 422 for an inverted date range", async () => {
    expect(
      await searchCatalog("dune", { dateFrom: "2024-06-01", dateTo: "2024-01-01" }),
    ).toEqual({ status: "invalid" });
  });

  it("returns status: invalid on a 422 for an inverted external rating range", async () => {
    expect(
      await searchCatalog("dune", { ratingExternalMin: 9, ratingExternalMax: 3 }),
    ).toEqual({ status: "invalid" });
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
