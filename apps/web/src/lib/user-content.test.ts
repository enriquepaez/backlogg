// @vitest-environment node
//
// Same MSW-backed pattern as `library.test.ts`'s `getUserLibrary`/
// `getUserProfile` tests: both helpers here own their `getApiClient()` call
// and status interpretation, so they're exercised end-to-end against the MSW
// mock server rather than a fake `ApiClient`.
import { createApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { MOCK_API_BASE_URL } from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const { getUserLists, getUserReviews } = await import("./user-content");

const aliceReviewsPage = {
  items: [
    {
      id: 1,
      item: { item_type: "MOVIE", title: "Dune", slug: "dune-2021", poster_url: null },
      score: 4,
      review_text: "Great adaptation.",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  limit: 10,
};

describe("getUserReviews", () => {
  it("returns ok with the paginated items on a 200", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/reviews`, () =>
        HttpResponse.json(aliceReviewsPage),
      ),
    );

    expect(await getUserReviews("alice")).toEqual({ ok: true, ...aliceReviewsPage });
  });

  it("forwards page/limit as query params", async () => {
    let capturedUrl: URL | undefined;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/reviews`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json(aliceReviewsPage);
      }),
    );

    await getUserReviews("alice", { page: 2, limit: 10 });

    expect(capturedUrl?.searchParams.get("page")).toBe("2");
    expect(capturedUrl?.searchParams.get("limit")).toBe("10");
  });

  it("returns ok: false on a 404 (unknown username)", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/reviews`, () =>
        HttpResponse.json({ detail: "Username not found" }, { status: 404 }),
      ),
    );

    expect(await getUserReviews("ghost")).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/reviews`, () => HttpResponse.error()),
    );

    expect(await getUserReviews("alice")).toEqual({ ok: false });
  });
});

const aliceLists = {
  lists: [
    {
      slug: "best-sci-fi",
      title: "Best sci-fi",
      description: "My favorite science fiction across media.",
      is_public: true,
      item_count: 12,
      created_at: "2026-05-20T10:00:00Z",
      updated_at: "2026-05-25T18:04:11Z",
    },
  ],
  total: 1,
};

describe("getUserLists", () => {
  it("returns ok with the lists on a 200", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/lists`, () => HttpResponse.json(aliceLists)),
    );

    expect(await getUserLists("alice")).toEqual({ ok: true, ...aliceLists });
  });

  it("forwards the given headers so the backend can resolve private lists for their owner", async () => {
    let forwardedAuth: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/lists`, ({ request }) => {
        forwardedAuth = request.headers.get("Authorization");
        return HttpResponse.json(aliceLists);
      }),
    );

    await getUserLists("alice", { Authorization: "Bearer the-token" });

    expect(forwardedAuth).toBe("Bearer the-token");
  });

  it("sends no Authorization header when called with no headers (default)", async () => {
    let forwardedAuth: string | null = "unset";
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/lists`, ({ request }) => {
        forwardedAuth = request.headers.get("Authorization");
        return HttpResponse.json(aliceLists);
      }),
    );

    await getUserLists("alice");

    expect(forwardedAuth).toBeNull();
  });

  it("returns ok: false on a 404 (unknown username)", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/lists`, () =>
        HttpResponse.json({ detail: "Username not found" }, { status: 404 }),
      ),
    );

    expect(await getUserLists("ghost")).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/lists`, () => HttpResponse.error()),
    );

    expect(await getUserLists("alice")).toEqual({ ok: false });
  });
});
