// @vitest-environment node
//
// Two groups, matching the two call shapes documented in `./library.ts`'s
// doc comment: `putLibraryStatus`/`deleteLibraryStatus`/
// `getViewerLibraryStatus` only dispatch to the right per-type templated
// operation (same spirit as `ratings.test.ts`, a minimal fake `ApiClient`
// suffices — the real path strings/response shapes are already enforced by
// `packages/api-client`'s generated types at compile time).
// `getUserLibrary`/`getUserProfile` are exercised end-to-end against the MSW
// mock server instead (same pattern as `search.test.ts`), since they own
// their `getApiClient()` call and status interpretation.
import { createApiClient, type ApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { MOCK_API_BASE_URL } from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const {
  deleteLibraryStatus,
  getUserLibrary,
  getUserProfile,
  getUserReviewScores,
  getViewerLibraryStatus,
  isLibraryStatus,
  putLibraryStatus,
} = await import("./library");

function fakeClient(): ApiClient {
  return {
    PUT: vi.fn().mockResolvedValue({
      data: { item_type: "MOVIE", slug: "dune-2021", status: "want", created_at: "t", updated_at: "t" },
      response: new Response(null, { status: 200 }),
    }),
    DELETE: vi.fn().mockResolvedValue({ response: new Response(null, { status: 204 }) }),
    GET: vi.fn().mockResolvedValue({
      data: { viewer_status: "want" },
      response: new Response(null, { status: 200 }),
    }),
  } as unknown as ApiClient;
}

describe("isLibraryStatus", () => {
  it("accepts the four valid statuses", () => {
    expect(isLibraryStatus("want")).toBe(true);
    expect(isLibraryStatus("in_progress")).toBe(true);
    expect(isLibraryStatus("completed")).toBe(true);
    expect(isLibraryStatus("dropped")).toBe(true);
  });

  it("rejects anything else", () => {
    expect(isLibraryStatus("watching")).toBe(false);
    expect(isLibraryStatus("")).toBe(false);
  });
});

describe("putLibraryStatus", () => {
  it.each([
    ["movie", "/v1/movies/{slug}/library"],
    ["series", "/v1/series/{slug}/library"],
    ["book", "/v1/books/{slug}/library"],
    ["game", "/v1/games/{slug}/library"],
  ] as const)("dispatches %s to %s", async (type, path) => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    await putLibraryStatus(client, headers, type, "some-slug", "want");

    expect(client.PUT).toHaveBeenCalledWith(path, {
      params: { path: { slug: "some-slug" } },
      body: { status: "want" },
      headers,
    });
  });
});

describe("deleteLibraryStatus", () => {
  it.each([
    ["movie", "/v1/movies/{slug}/library"],
    ["series", "/v1/series/{slug}/library"],
    ["book", "/v1/books/{slug}/library"],
    ["game", "/v1/games/{slug}/library"],
  ] as const)("dispatches %s to %s", async (type, path) => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    await deleteLibraryStatus(client, headers, type, "some-slug");

    expect(client.DELETE).toHaveBeenCalledWith(path, {
      params: { path: { slug: "some-slug" } },
      headers,
    });
  });
});

describe("getViewerLibraryStatus", () => {
  it.each([
    ["movie", "/v1/movies/{slug}"],
    ["series", "/v1/series/{slug}"],
    ["book", "/v1/books/{slug}"],
    ["game", "/v1/games/{slug}"],
  ] as const)("dispatches %s to %s", async (type, path) => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    const result = await getViewerLibraryStatus(client, headers, type, "some-slug");

    expect(client.GET).toHaveBeenCalledWith(path, {
      params: { path: { slug: "some-slug" } },
      headers,
    });
    expect(result.data).toEqual({ viewer_status: "want" });
  });
});

const aliceProfile = {
  username: "alice",
  display_name: "Alice",
  bio: null,
  avatar_url: null,
  follower_count: 2,
  following_count: 1,
  library_counts: { want: 1, in_progress: 2, completed: 3, dropped: 0 },
};

const aliceLibraryPage = {
  items: [
    {
      item: {
        item_type: "MOVIE",
        title: "Dune",
        slug: "dune-2021",
        poster_url: null,
        release_date: "2021-10-22",
        rating_external: 7.8,
      },
      status: "completed",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  limit: 24,
};

describe("getUserLibrary", () => {
  it("returns ok with the paginated items on a 200", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/library`, () =>
        HttpResponse.json(aliceLibraryPage),
      ),
    );

    expect(await getUserLibrary("alice")).toEqual({ ok: true, ...aliceLibraryPage });
  });

  it("forwards status/type/page/limit as query params", async () => {
    let capturedUrl: URL | undefined;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/library`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json(aliceLibraryPage);
      }),
    );

    await getUserLibrary("alice", { status: "completed", type: "movie", page: 2, limit: 24 });

    expect(capturedUrl?.searchParams.get("status")).toBe("completed");
    expect(capturedUrl?.searchParams.get("type")).toBe("movie");
    expect(capturedUrl?.searchParams.get("page")).toBe("2");
    expect(capturedUrl?.searchParams.get("limit")).toBe("24");
  });

  it("returns ok: false on a 404 (unknown username)", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/library`, () =>
        HttpResponse.json({ detail: "Username not found" }, { status: 404 }),
      ),
    );

    expect(await getUserLibrary("ghost")).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/library`, () => HttpResponse.error()),
    );

    expect(await getUserLibrary("alice")).toEqual({ ok: false });
  });
});

const aliceReviewsPage = {
  items: [
    {
      id: 1,
      item: { item_type: "MOVIE", title: "Dune", slug: "dune-2021", poster_url: null },
      score: 4.5,
      review_text: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
    {
      id: 2,
      item: { item_type: "BOOK", title: "Dune", slug: "dune", poster_url: null },
      score: null,
      review_text: "no score, review only",
      created_at: "2026-01-02T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    },
  ],
  total: 2,
  page: 1,
  limit: 100,
};

describe("getUserReviewScores", () => {
  it("builds a score map keyed by item_type:slug, skipping null scores", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/reviews`, () =>
        HttpResponse.json(aliceReviewsPage),
      ),
    );

    const scores = await getUserReviewScores("alice");

    expect(scores).toEqual(new Map([["MOVIE:dune-2021", 4.5]]));
  });

  it("requests the max scan limit", async () => {
    let capturedUrl: URL | undefined;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/reviews`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json(aliceReviewsPage);
      }),
    );

    await getUserReviewScores("alice");

    expect(capturedUrl?.searchParams.get("limit")).toBe("100");
  });

  it("returns an empty map on a non-200 response", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/reviews`, () =>
        HttpResponse.json({ detail: "Username not found" }, { status: 404 }),
      ),
    );

    expect(await getUserReviewScores("ghost")).toEqual(new Map());
  });

  it("returns an empty map when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/reviews`, () => HttpResponse.error()),
    );

    expect(await getUserReviewScores("alice")).toEqual(new Map());
  });
});

describe("getUserProfile", () => {
  it("returns status: ok with the profile on a 200", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username`, () => HttpResponse.json(aliceProfile)),
    );

    expect(await getUserProfile("alice")).toEqual({ status: "ok", profile: aliceProfile });
  });

  it("returns status: not-found on a 404", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username`, () =>
        HttpResponse.json({ detail: "Username not found" }, { status: 404 }),
      ),
    );

    expect(await getUserProfile("ghost")).toEqual({ status: "not-found" });
  });

  it("returns status: error on an unexpected non-200/404 response", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getUserProfile("alice")).toEqual({ status: "error" });
  });

  it("returns status: error when the network fails", async () => {
    server.use(http.get(`${MOCK_API_BASE_URL}/v1/users/:username`, () => HttpResponse.error()));

    expect(await getUserProfile("alice")).toEqual({ status: "error" });
  });
});
