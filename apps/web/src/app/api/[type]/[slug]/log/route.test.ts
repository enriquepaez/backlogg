// @vitest-environment node
//
// Same rationale as `[type]/[slug]/rating/route.test.ts`: `apiFetch`/
// `getCurrentUser` depend on `next/headers`' request-scoped `cookies()`,
// which only works inside a real Next.js request, so both are mocked here.
// `postLog`/`listLog`/`getUserLog` (`@/lib/activity-log`) are mocked too so
// this file only exercises the route's own branching, not the per-type
// dispatch already covered by `activity-log.test.ts`.
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

const postLogMock = vi.fn();
const listLogMock = vi.fn();
const getUserLogMock = vi.fn();
vi.mock("@/lib/activity-log", () => ({
  postLog: (...args: unknown[]) => postLogMock(...args),
  listLog: (...args: unknown[]) => listLogMock(...args),
  getUserLog: (...args: unknown[]) => getUserLogMock(...args),
}));

const { GET, POST } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(type: string, slug: string) {
  return { params: Promise.resolve({ type, slug }) };
}

function postRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/movie/dune-2021/log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const alice = { username: "alice", email: "a@example.com", display_name: null, bio: null, avatar_url: null, email_verified: true };
const savedLog = { id: 7, item_type: "MOVIE", slug: "dune-2021", logged_on: "2026-01-01", rewatch: false, note: null, created_at: "t" };
const publicLogPage = { items: [savedLog], total: 1, page: 1, limit: 20 };

beforeEach(() => {
  apiFetchMock.mockClear();
  getCurrentUserMock.mockClear();
  postLogMock.mockClear();
  listLogMock.mockClear();
  getUserLogMock.mockClear();
});

describe("GET /api/{type}/{slug}/log", () => {
  it("returns 400 for an invalid type without touching the session", async () => {
    const response = await GET(new Request("http://x"), params("tv-show", "dune-2021"));

    expect(response.status).toBe(400);
    expect(listLogMock).not.toHaveBeenCalled();
  });

  it("returns 404 when the item-scoped listing fails to find the slug", async () => {
    listLogMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await GET(new Request("http://x"), params("movie", "unknown-slug"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns authenticated:false and an empty mine[] when there is no session", async () => {
    listLogMock.mockResolvedValueOnce({ data: publicLogPage, response: backendResponse(200) });
    getCurrentUserMock.mockResolvedValueOnce(null);

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ ...publicLogPage, authenticated: false, mine: [] });
    expect(getUserLogMock).not.toHaveBeenCalled();
  });

  it("resolves the caller's own logs for this item from GET /v1/users/{username}/log, filtered by item_type/slug", async () => {
    listLogMock.mockResolvedValueOnce({ data: publicLogPage, response: backendResponse(200) });
    getCurrentUserMock.mockResolvedValueOnce(alice);
    getUserLogMock.mockResolvedValueOnce({
      data: {
        items: [
          { id: 7, item: { item_type: "MOVIE", title: "Dune", slug: "dune-2021", poster_url: null }, logged_on: "2026-01-01", rewatch: false, note: null, created_at: "t" },
          { id: 8, item: { item_type: "SERIES", title: "Other", slug: "dune-2021", poster_url: null }, logged_on: "2026-01-02", rewatch: false, note: null, created_at: "t" },
          { id: 9, item: { item_type: "MOVIE", title: "Another", slug: "other-slug", poster_url: null }, logged_on: "2026-01-03", rewatch: false, note: null, created_at: "t" },
        ],
        total: 3,
        page: 1,
        limit: 100,
      },
      response: backendResponse(200),
    });

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.authenticated).toBe(true);
    expect(body.mine).toEqual([{ id: 7, logged_on: "2026-01-01", rewatch: false, note: null }]);
    expect(getUserLogMock).toHaveBeenCalledWith({ name: "fake-api-client" }, "alice", { limit: 100 });
  });

  it("degrades to an empty mine[] when the own-log scan itself fails", async () => {
    listLogMock.mockResolvedValueOnce({ data: publicLogPage, response: backendResponse(200) });
    getCurrentUserMock.mockResolvedValueOnce(alice);
    getUserLogMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.authenticated).toBe(true);
    expect(body.mine).toEqual([]);
  });

  it("forwards page/limit query params to listLog", async () => {
    listLogMock.mockResolvedValueOnce({ data: publicLogPage, response: backendResponse(200) });
    getCurrentUserMock.mockResolvedValueOnce(null);

    await GET(new Request("http://x/api/movie/dune-2021/log?page=2&limit=10"), params("movie", "dune-2021"));

    expect(listLogMock).toHaveBeenCalledWith({ name: "fake-api-client" }, "movie", "dune-2021", { page: 2, limit: 10 });
  });
});

describe("POST /api/{type}/{slug}/log", () => {
  it("returns 400 for an invalid type without calling apiFetch", async () => {
    const response = await POST(postRequest({ rewatch: true }), params("album", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 for malformed JSON", async () => {
    const request = new Request("http://x", { method: "POST", body: "not json" });
    const response = await POST(request, params("movie", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it.each([
    { logged_on: 123 },
    { rewatch: "yes" },
    { note: 123 },
  ])("returns 400 for a malformed body %p", async (payload) => {
    const response = await POST(postRequest(payload), params("movie", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("defaults rewatch to false and note/logged_on to null when omitted", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        postLogMock.mockResolvedValue({ data: savedLog, response: backendResponse(201) });
        const result = await call({ name: "fake-client" }, "the-token");
        expect(postLogMock).toHaveBeenCalledWith(
          { name: "fake-client" },
          { Authorization: "Bearer the-token" },
          "movie",
          "dune-2021",
          { logged_on: null, rewatch: false, note: null },
        );
        return result;
      },
    );

    const response = await POST(postRequest({}), params("movie", "dune-2021"));
    expect(response.status).toBe(201);
  });

  it("returns the created log entry on a 201 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: savedLog, response: backendResponse(201) });

    const response = await POST(
      postRequest({ logged_on: "2026-01-01", rewatch: true, note: "Great rewatch" }),
      params("movie", "dune-2021"),
    );
    const body = await response.json();

    expect(response.status).toBe(201);
    expect(body).toEqual(savedLog);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await POST(postRequest({}), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the slug doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await POST(postRequest({}), params("movie", "unknown"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 422 for a future logged_on rejected by the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(422) });

    const response = await POST(postRequest({ logged_on: "2999-01-01" }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body).toEqual({ error: "validation_error" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await POST(postRequest({}), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "log_failed" });
  });
});
