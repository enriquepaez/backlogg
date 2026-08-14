// @vitest-environment node
//
// Same rationale as `../rating/route.test.ts`: `getCurrentUser`/`apiFetch`
// depend on `next/headers`' request-scoped `cookies()`, which only works
// inside a real Next.js request, so both are mocked here. `listRatings`
// (`@/lib/ratings`) is mocked too so this file only exercises the route's
// own branching (query parsing, `authenticated` reporting, error
// passthrough, token forwarding), not the per-type dispatch already covered
// by `ratings.test.ts`. `apiFetch` is mocked to invoke its callback with a
// fake client and a configurable token, same pattern as
// `../../reviews/[id]/like/route.test.ts`.
import { beforeEach, describe, expect, it, vi } from "vitest";

const getCurrentUserMock = vi.fn();
const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  getCurrentUser: (...args: unknown[]) => getCurrentUserMock(...args),
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const listRatingsMock = vi.fn();
vi.mock("@/lib/ratings", () => ({
  listRatings: (...args: unknown[]) => listRatingsMock(...args),
}));

const { GET } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(type: string, slug: string) {
  return { params: Promise.resolve({ type, slug }) };
}

function request(query = ""): Request {
  return new Request(`http://localhost:3000/api/movie/dune-2021/ratings${query}`);
}

const alice = { username: "alice", email: "a@example.com", display_name: null, bio: null, avatar_url: null, email_verified: true };
const page = {
  items: [
    { id: 1, user: { username: "bob", display_name: "Bob", avatar_url: null }, score: 4, review_text: "Great", like_count: 2, liked_by_viewer: false, created_at: "t", updated_at: "t" },
  ],
  total: 1,
  page: 1,
  limit: 10,
};

/**
 * Wires `apiFetch` to call through to the real callback with a fake client
 * and `token`, and `listRatings` to resolve with `result` — so
 * `listRatingsMock` assertions below see exactly what the route passed
 * through, including the `Authorization` header built from `token`.
 */
function mockListRatings(result: { data?: unknown; response: Response }, token?: string) {
  listRatingsMock.mockResolvedValueOnce(result);
  apiFetchMock.mockImplementationOnce(
    async (call: (client: unknown, token: string | undefined) => unknown) =>
      call({ name: "fake-api-client" }, token),
  );
}

beforeEach(() => {
  getCurrentUserMock.mockClear();
  apiFetchMock.mockClear();
  listRatingsMock.mockClear();
});

describe("GET /api/{type}/{slug}/ratings", () => {
  it("returns 400 for an invalid type without touching the session or listRatings", async () => {
    const response = await GET(request(), params("tv-show", "dune-2021"));

    expect(response.status).toBe(400);
    expect(getCurrentUserMock).not.toHaveBeenCalled();
    expect(listRatingsMock).not.toHaveBeenCalled();
  });

  it("defaults to page=1, limit=10 with no query params", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);
    mockListRatings({ data: page, response: backendResponse(200) });

    await GET(request(), params("movie", "dune-2021"));

    expect(listRatingsMock).toHaveBeenCalledWith(
      { name: "fake-api-client" },
      "movie",
      "dune-2021",
      { page: 1, limit: 10 },
      {},
    );
  });

  it("forwards valid page/limit query params", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);
    mockListRatings({ data: page, response: backendResponse(200) });

    await GET(request("?page=3&limit=25"), params("movie", "dune-2021"));

    expect(listRatingsMock).toHaveBeenCalledWith(
      { name: "fake-api-client" },
      "movie",
      "dune-2021",
      { page: 3, limit: 25 },
      {},
    );
  });

  it.each(["0", "-1", "1.5", "abc"])(
    "falls back to page=1 for an invalid page value %p",
    async (rawPage) => {
      getCurrentUserMock.mockResolvedValueOnce(null);
      mockListRatings({ data: page, response: backendResponse(200) });

      await GET(request(`?page=${rawPage}`), params("movie", "dune-2021"));

      expect(listRatingsMock).toHaveBeenCalledWith(
        { name: "fake-api-client" },
        "movie",
        "dune-2021",
        { page: 1, limit: 10 },
        {},
      );
    },
  );

  it("caps limit at 100 even when a larger value is requested", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);
    mockListRatings({ data: page, response: backendResponse(200) });

    await GET(request("?limit=1000"), params("movie", "dune-2021"));

    expect(listRatingsMock).toHaveBeenCalledWith(
      { name: "fake-api-client" },
      "movie",
      "dune-2021",
      { page: 1, limit: 100 },
      {},
    );
  });

  it("reports authenticated:true and the page data when there is a valid session", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    mockListRatings({ data: page, response: backendResponse(200) });

    const response = await GET(request(), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: true, ...page });
  });

  it("reports authenticated:false when there is no session", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);
    mockListRatings({ data: page, response: backendResponse(200) });

    const response = await GET(request(), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: false, ...page });
  });

  it("forwards the caller's access token as an Authorization header so liked_by_viewer reflects the real viewer", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    mockListRatings({ data: page, response: backendResponse(200) }, "alice-token");

    await GET(request(), params("movie", "dune-2021"));

    expect(listRatingsMock).toHaveBeenCalledWith(
      { name: "fake-api-client" },
      "movie",
      "dune-2021",
      { page: 1, limit: 10 },
      { Authorization: "Bearer alice-token" },
    );
  });

  it("sends no Authorization header for an anonymous caller", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);
    mockListRatings({ data: page, response: backendResponse(200) }, undefined);

    await GET(request(), params("movie", "dune-2021"));

    expect(listRatingsMock).toHaveBeenCalledWith(
      { name: "fake-api-client" },
      "movie",
      "dune-2021",
      { page: 1, limit: 10 },
      {},
    );
  });

  it("returns 404 when the slug doesn't exist", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);
    mockListRatings({ response: backendResponse(404) });

    const response = await GET(request(), params("movie", "unknown-slug"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "list_ratings_failed" });
  });

  it("collapses any other backend failure to a generic error with the same status code", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);
    mockListRatings({ response: backendResponse(500) });

    const response = await GET(request(), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "list_ratings_failed" });
  });
});
