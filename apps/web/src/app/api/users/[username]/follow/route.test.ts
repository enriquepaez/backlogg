// @vitest-environment node
//
// Same rationale as `../../[type]/[slug]/library/route.test.ts`: `apiFetch`/
// `getCurrentUser` depend on `next/headers`' request-scoped `cookies()`, so
// both are mocked, along with `@/lib/follows` so this file only exercises
// the route's own branching (including the GET scan), not the dispatch
// already covered by `follows.test.ts`.
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
}));

const followUserMock = vi.fn();
const unfollowUserMock = vi.fn();
const getFollowingMock = vi.fn();
vi.mock("@/lib/follows", () => ({
  followUser: (...args: unknown[]) => followUserMock(...args),
  unfollowUser: (...args: unknown[]) => unfollowUserMock(...args),
  getFollowing: (...args: unknown[]) => getFollowingMock(...args),
}));

const { GET, POST, DELETE } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(username: string) {
  return { params: Promise.resolve({ username }) };
}

beforeEach(() => {
  apiFetchMock.mockClear();
  getCurrentUserMock.mockClear();
  followUserMock.mockClear();
  unfollowUserMock.mockClear();
  getFollowingMock.mockClear();
});

const alice = { username: "alice", email: "a@example.com", display_name: null, bio: null, avatar_url: null, email_verified: true };

describe("GET /api/users/{username}/follow", () => {
  it("returns authenticated:false, following:false without scanning when there is no session", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);

    const response = await GET(new Request("http://x"), params("bob"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: false, following: false });
    expect(getFollowingMock).not.toHaveBeenCalled();
  });

  it("returns following:true when the target username is in the first page of the viewer's following", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    getFollowingMock.mockResolvedValueOnce({
      ok: true,
      items: [{ username: "bob", display_name: null, avatar_url: null }],
      total: 1,
      page: 1,
      limit: 100,
    });

    const response = await GET(new Request("http://x"), params("bob"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: true, following: true });
    expect(getFollowingMock).toHaveBeenCalledWith("alice", { limit: 100 });
  });

  it("returns following:false when the target username isn't in the viewer's following", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    getFollowingMock.mockResolvedValueOnce({ ok: true, items: [], total: 0, page: 1, limit: 100 });

    const response = await GET(new Request("http://x"), params("bob"));
    const body = await response.json();

    expect(body).toEqual({ authenticated: true, following: false });
  });

  it("returns following:false when the scan itself fails", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    getFollowingMock.mockResolvedValueOnce({ ok: false });

    const response = await GET(new Request("http://x"), params("bob"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: true, following: false });
  });
});

describe("POST /api/users/{username}/follow", () => {
  it("returns 204 on a 204 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(204) });

    const response = await POST(new Request("http://x"), params("bob"));

    expect(response.status).toBe(204);
  });

  it("forwards the username to followUser with headers built from the access token", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        followUserMock.mockResolvedValue({ response: backendResponse(204) });
        const result = await call({ name: "fake-client" }, "the-token");
        expect(followUserMock).toHaveBeenCalledWith(
          { name: "fake-client" },
          { Authorization: "Bearer the-token" },
          "bob",
        );
        return result;
      },
    );

    const response = await POST(new Request("http://x"), params("bob"));
    expect(response.status).toBe(204);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await POST(new Request("http://x"), params("bob"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the username doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await POST(new Request("http://x"), params("ghost"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 422 for a self-follow attempt", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(422) });

    const response = await POST(new Request("http://x"), params("alice"));
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body).toEqual({ error: "validation_error" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await POST(new Request("http://x"), params("bob"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "follow_failed" });
  });
});

describe("DELETE /api/users/{username}/follow", () => {
  it("returns 204 on a 204 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(204) });

    const response = await DELETE(new Request("http://x"), params("bob"));

    expect(response.status).toBe(204);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await DELETE(new Request("http://x"), params("bob"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the username doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await DELETE(new Request("http://x"), params("ghost"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await DELETE(new Request("http://x"), params("bob"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "unfollow_failed" });
  });
});
