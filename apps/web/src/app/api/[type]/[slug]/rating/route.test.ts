// @vitest-environment node
//
// Same rationale as `src/app/api/users/me/route.test.ts`: `apiFetch`/
// `getCurrentUser` depend on `next/headers`' request-scoped `cookies()`,
// which only works inside a real Next.js request, so both are mocked here.
// `listRatings`/`putRating`/`deleteRating` (`@/lib/ratings`) are mocked too
// so this file only exercises the route's own branching, not the per-type
// dispatch already covered by `ratings.test.ts`. `revalidateTag` (`next/cache`)
// and `itemDetailCacheTag` (`@/lib/catalog`) are mocked so the `PUT`/`DELETE`
// bugfix below (see their describe blocks) can assert the exact call without
// pulling in the rest of `@/lib/catalog` (itself pulling in `@/lib/auth/session`).
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
const getCurrentUserMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  getCurrentUser: (...args: unknown[]) => getCurrentUserMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  getApiClient: () => ({ name: "fake-api-client" }),
}));

const listRatingsMock = vi.fn();
const putRatingMock = vi.fn();
const deleteRatingMock = vi.fn();
vi.mock("@/lib/ratings", () => ({
  listRatings: (...args: unknown[]) => listRatingsMock(...args),
  putRating: (...args: unknown[]) => putRatingMock(...args),
  deleteRating: (...args: unknown[]) => deleteRatingMock(...args),
}));

const revalidateTagMock = vi.fn();
vi.mock("next/cache", () => ({
  revalidateTag: (...args: unknown[]) => revalidateTagMock(...args),
}));

vi.mock("@/lib/catalog", () => ({
  itemDetailCacheTag: (type: string, slug: string) => `item-detail:${type}:${slug}`,
}));

const { GET, PUT, DELETE } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(type: string, slug: string) {
  return { params: Promise.resolve({ type, slug }) };
}

function putRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/movie/dune-2021/rating", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  apiFetchMock.mockClear();
  getCurrentUserMock.mockClear();
  listRatingsMock.mockClear();
  putRatingMock.mockClear();
  deleteRatingMock.mockClear();
  revalidateTagMock.mockClear();
});

const alice = { username: "alice", email: "a@example.com", display_name: null, bio: null, avatar_url: null, email_verified: true };
const bob = { user: { username: "bob", display_name: "Bob", avatar_url: null }, id: 1, score: 3, review_text: null, like_count: 0, created_at: "t", updated_at: "t" };
const aliceRating = { user: { username: "alice", display_name: null, avatar_url: null }, id: 2, score: 5, review_text: "Loved it", like_count: 0, created_at: "t", updated_at: "t" };

describe("GET /api/{type}/{slug}/rating", () => {
  it("returns 400 for an invalid type without touching the session", async () => {
    const response = await GET(new Request("http://x"), params("tv-show", "dune-2021"));

    expect(response.status).toBe(400);
    expect(getCurrentUserMock).not.toHaveBeenCalled();
  });

  it("returns authenticated:false without calling listRatings when there is no session", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: false, rating: null });
    expect(listRatingsMock).not.toHaveBeenCalled();
  });

  it("finds and returns the caller's own rating among the item's ratings", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    listRatingsMock.mockResolvedValueOnce({
      data: { items: [bob, aliceRating], total: 2, page: 1, limit: 100 },
      response: backendResponse(200),
    });

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: true, rating: aliceRating });
  });

  it("returns rating:null when the caller has no rating among the scanned page", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    listRatingsMock.mockResolvedValueOnce({
      data: { items: [bob], total: 1, page: 1, limit: 100 },
      response: backendResponse(200),
    });

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: true, rating: null });
  });

  it("propagates a failure from listRatings", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    listRatingsMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await GET(new Request("http://x"), params("movie", "unknown-slug"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "list_ratings_failed" });
  });
});

describe("PUT /api/{type}/{slug}/rating", () => {
  it("returns 400 for an invalid type without calling apiFetch", async () => {
    const response = await PUT(putRequest({ score: 4, review_text: null }), params("album", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 for malformed JSON", async () => {
    const request = new Request("http://x", { method: "PUT", body: "not json" });
    const response = await PUT(request, params("movie", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it.each([0, 6, 1.25, "5"])("returns 400 for an out-of-range/invalid score %p", async (score) => {
    const response = await PUT(putRequest({ score, review_text: null }), params("movie", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  // Bugfix (post-review, FE-44): half-point scores (steps of 0.5, e.g. 3.5)
  // are valid per the backend schema (`ge=1, le=5, multiple_of=0.5`,
  // `backlogg/ratings/schemas.py`) and must reach `putRating`, not be
  // rejected by `isValidScore` as if they were non-integers.
  it("accepts a half-point score (3.5) and forwards it to putRating", async () => {
    const halfScoreRating = { ...aliceRating, score: 3.5 };
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        putRatingMock.mockResolvedValue({ data: halfScoreRating, response: backendResponse(200) });
        return call({ name: "fake-client" }, "the-token");
      },
    );

    const response = await PUT(putRequest({ score: 3.5, review_text: null }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(putRatingMock).toHaveBeenCalledWith(
      { name: "fake-client" },
      { Authorization: "Bearer the-token" },
      "movie",
      "dune-2021",
      { score: 3.5, review_text: null },
    );
    expect(response.status).toBe(200);
    expect(body).toEqual(halfScoreRating);
  });

  it("returns the updated rating on a 200 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: aliceRating, response: backendResponse(200) });

    const response = await PUT(putRequest({ score: 5, review_text: "Loved it" }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(aliceRating);
  });

  // Bugfix (post-FE-18 QA): a successful upsert must invalidate the item
  // detail page's cached aggregates (`itemDetailCacheTag`'s doc comment in
  // `src/lib/catalog.ts`) — otherwise "Backlogg rating" stays stale for up to
  // `ITEM_REVALIDATE_SECONDS` (1h) after the caller's own score changes it.
  it("revalidates the item detail cache tag on a successful upsert", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: aliceRating, response: backendResponse(200) });

    await PUT(putRequest({ score: 5, review_text: "Loved it" }), params("movie", "dune-2021"));

    expect(revalidateTagMock).toHaveBeenCalledTimes(1);
    expect(revalidateTagMock).toHaveBeenCalledWith("item-detail:movie:dune-2021", { expire: 0 });
  });

  it.each([401, 404, 422, 500])(
    "does not revalidate the item detail cache tag on a %i from the backend",
    async (status) => {
      apiFetchMock.mockResolvedValueOnce({ response: backendResponse(status) });

      await PUT(putRequest({ score: 5, review_text: null }), params("movie", "dune-2021"));

      expect(revalidateTagMock).not.toHaveBeenCalled();
    },
  );

  it("forwards score/review_text to putRating with headers built from the access token", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        putRatingMock.mockResolvedValue({ data: aliceRating, response: backendResponse(200) });
        const result = await call({ name: "fake-client" }, "the-token");
        expect(putRatingMock).toHaveBeenCalledWith(
          { name: "fake-client" },
          { Authorization: "Bearer the-token" },
          "movie",
          "dune-2021",
          { score: 5, review_text: "Loved it" },
        );
        return result;
      },
    );

    const response = await PUT(putRequest({ score: 5, review_text: "Loved it" }), params("movie", "dune-2021"));
    expect(response.status).toBe(200);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await PUT(putRequest({ score: 5, review_text: null }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the slug doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await PUT(putRequest({ score: 5, review_text: null }), params("movie", "unknown"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 422 for a backend validation failure", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(422) });

    const response = await PUT(putRequest({ score: 5, review_text: null }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body).toEqual({ error: "validation_error" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await PUT(putRequest({ score: 5, review_text: null }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "rate_failed" });
  });
});

describe("DELETE /api/{type}/{slug}/rating", () => {
  it("returns 400 for an invalid type without calling apiFetch", async () => {
    const response = await DELETE(new Request("http://x"), params("album", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 204 on a 204 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(204) });

    const response = await DELETE(new Request("http://x"), params("movie", "dune-2021"));

    expect(response.status).toBe(204);
  });

  // Same bugfix as the PUT case above — deleting a rating changes the item's
  // aggregates too.
  it("revalidates the item detail cache tag on a successful delete", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(204) });

    await DELETE(new Request("http://x"), params("movie", "dune-2021"));

    expect(revalidateTagMock).toHaveBeenCalledTimes(1);
    expect(revalidateTagMock).toHaveBeenCalledWith("item-detail:movie:dune-2021", { expire: 0 });
  });

  it.each([401, 404, 500])(
    "does not revalidate the item detail cache tag on a %i from the backend",
    async (status) => {
      apiFetchMock.mockResolvedValueOnce({ response: backendResponse(status) });

      await DELETE(new Request("http://x"), params("movie", "dune-2021"));

      expect(revalidateTagMock).not.toHaveBeenCalled();
    },
  );

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await DELETE(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the caller has no rating for the item", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await DELETE(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await DELETE(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "delete_rating_failed" });
  });
});
