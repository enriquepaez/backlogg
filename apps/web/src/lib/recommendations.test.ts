// @vitest-environment node
//
// `getRecommendations` is built on `apiFetch` (`@/lib/api-fetch`), which
// depends on `next/headers`' request-scoped `cookies()` and only works
// inside a real Next.js request — same rationale as `./feed.test.ts`: mock
// `apiFetch`/`authHeader` directly rather than exercise the real
// cookie-reading/refresh machinery.
import { describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const { RECOMMENDATIONS_FALLBACK_REASON, getRecommendations, recommendationItemType } =
  await import("./recommendations");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

const recommendationsPage = {
  results: [
    {
      item_type: "MOVIE",
      title: "Blade Runner 2049",
      slug: "blade-runner-2049",
      poster_url: "https://image.tmdb.org/t/p/w500/br2049.jpg",
      release_date: "2017-10-06",
      rating_external: 8.0,
      reason: "Because you rated Dune",
    },
  ],
  page: 1,
  limit: 20,
};

describe("getRecommendations", () => {
  it("returns ok with the paginated results on a 200, forwarding type/page/limit and the bearer header", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const client = {
          GET: vi.fn().mockResolvedValue({ data: recommendationsPage, response: backendResponse(200) }),
        };
        const result = await call(client, "the-token");
        expect(client.GET).toHaveBeenCalledWith("/v1/recommendations", {
          params: { query: { type: "movie", page: 2, limit: 20 } },
          headers: { Authorization: "Bearer the-token" },
        });
        return result;
      },
    );

    expect(await getRecommendations({ type: "movie", page: 2, limit: 20 })).toEqual({
      ok: true,
      ...recommendationsPage,
    });
  });

  it("returns ok: false on a 401 (no valid session)", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    expect(await getRecommendations()).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    apiFetchMock.mockRejectedValueOnce(new Error("network down"));

    expect(await getRecommendations()).toEqual({ ok: false });
  });
});

describe("recommendationItemType", () => {
  it("lowercases the backend's item_type for routing", () => {
    expect(recommendationItemType({ ...recommendationsPage.results[0], item_type: "MOVIE" })).toBe(
      "movie",
    );
    expect(recommendationItemType({ ...recommendationsPage.results[0], item_type: "SERIES" })).toBe(
      "series",
    );
    expect(recommendationItemType({ ...recommendationsPage.results[0], item_type: "BOOK" })).toBe(
      "book",
    );
    expect(recommendationItemType({ ...recommendationsPage.results[0], item_type: "GAME" })).toBe(
      "game",
    );
  });
});

describe("RECOMMENDATIONS_FALLBACK_REASON", () => {
  it("matches the backend's no-seeds fallback reason string", () => {
    expect(RECOMMENDATIONS_FALLBACK_REASON).toBe("Popular right now");
  });
});
