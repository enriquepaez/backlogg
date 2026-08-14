// @vitest-environment node
//
// `getFeed` is built on `apiFetch` (`@/lib/api-fetch`), which depends on
// `next/headers`' request-scoped `cookies()` and only works inside a real
// Next.js request — same rationale as
// `src/app/api/[type]/[slug]/rating/route.test.ts`: mock `apiFetch`/
// `authHeader` directly rather than exercise the real cookie-reading/refresh
// machinery. `isFeedTab`/`FEED_TABS`/`DEFAULT_FEED_TAB` are plain re-exports
// of `./feed-types.ts` — tested here (rather than in a dedicated
// `feed-types.test.ts`) the same way `library.test.ts` covers
// `isLibraryStatus` alongside the fetch helpers in `./library.ts`.
import { describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const { DEFAULT_FEED_TAB, FEED_TABS, getFeed, isFeedTab } = await import("./feed");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

describe("isFeedTab", () => {
  it("accepts the two valid tabs", () => {
    expect(isFeedTab("following")).toBe(true);
    expect(isFeedTab("popular")).toBe(true);
  });

  it("rejects anything else", () => {
    expect(isFeedTab("trending")).toBe(false);
    expect(isFeedTab("")).toBe(false);
  });
});

describe("FEED_TABS / DEFAULT_FEED_TAB", () => {
  it("lists both tabs, with following as the default", () => {
    expect(FEED_TABS).toEqual(["following", "popular"]);
    expect(DEFAULT_FEED_TAB).toBe("following");
  });
});

const feedPage = {
  items: [
    {
      id: 1,
      author: { username: "bob", display_name: "Bob", avatar_url: null },
      item: { item_type: "MOVIE", title: "Dune", slug: "dune-2021", poster_url: null },
      score: 5,
      review_text: "Great",
      like_count: 3,
      created_at: "2026-05-25T18:04:11Z",
    },
  ],
  total: 1,
  page: 2,
  limit: 20,
};

describe("getFeed", () => {
  it("returns ok with the paginated items on a 200, forwarding tab/page/limit and the bearer header", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const client = {
          GET: vi.fn().mockResolvedValue({ data: feedPage, response: backendResponse(200) }),
        };
        const result = await call(client, "the-token");
        expect(client.GET).toHaveBeenCalledWith("/v1/feed", {
          params: { query: { tab: "popular", page: 2, limit: 20 } },
          headers: { Authorization: "Bearer the-token" },
        });
        return result;
      },
    );

    expect(await getFeed({ tab: "popular", page: 2, limit: 20 })).toEqual({ ok: true, ...feedPage });
  });

  it("returns ok: false on a 401 (no valid session)", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    expect(await getFeed({ tab: "following" })).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    apiFetchMock.mockRejectedValueOnce(new Error("network down"));

    expect(await getFeed({ tab: "following" })).toEqual({ ok: false });
  });
});
