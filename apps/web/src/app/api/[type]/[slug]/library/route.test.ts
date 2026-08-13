// @vitest-environment node
//
// Same rationale as `../rating/route.test.ts`: `apiFetch`/`getCurrentUser`
// depend on `next/headers`' request-scoped `cookies()`, so both are mocked.
// `putLibraryStatus`/`deleteLibraryStatus`/`getViewerLibraryStatus`
// (`@/lib/library`) are mocked too so this file only exercises the route's
// own branching, not the per-type dispatch already covered by
// `library.test.ts`.
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

const putLibraryStatusMock = vi.fn();
const deleteLibraryStatusMock = vi.fn();
const getViewerLibraryStatusMock = vi.fn();
vi.mock("@/lib/library", () => ({
  putLibraryStatus: (...args: unknown[]) => putLibraryStatusMock(...args),
  deleteLibraryStatus: (...args: unknown[]) => deleteLibraryStatusMock(...args),
  getViewerLibraryStatus: (...args: unknown[]) => getViewerLibraryStatusMock(...args),
  isLibraryStatus: (value: string) =>
    (["want", "in_progress", "completed", "dropped"] as readonly string[]).includes(value),
}));

const { GET, PUT, DELETE } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(type: string, slug: string) {
  return { params: Promise.resolve({ type, slug }) };
}

function putRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/movie/dune-2021/library", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  apiFetchMock.mockClear();
  getCurrentUserMock.mockClear();
  putLibraryStatusMock.mockClear();
  deleteLibraryStatusMock.mockClear();
  getViewerLibraryStatusMock.mockClear();
});

const alice = { username: "alice", email: "a@example.com", display_name: null, bio: null, avatar_url: null, email_verified: true };

const libraryStatusOut = {
  item_type: "MOVIE",
  slug: "dune-2021",
  status: "want",
  created_at: "t",
  updated_at: "t",
};

describe("GET /api/{type}/{slug}/library", () => {
  it("returns 400 for an invalid type without touching the session", async () => {
    const response = await GET(new Request("http://x"), params("tv-show", "dune-2021"));

    expect(response.status).toBe(400);
    expect(getCurrentUserMock).not.toHaveBeenCalled();
  });

  it("returns authenticated:false, status:null without calling apiFetch when there is no session", async () => {
    getCurrentUserMock.mockResolvedValueOnce(null);

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: false, status: null });
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns the caller's viewer_status on a 200", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    apiFetchMock.mockResolvedValueOnce({ data: { viewer_status: "want" }, response: backendResponse(200) });

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: true, status: "want" });
  });

  it("normalizes a missing/null viewer_status to null", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    apiFetchMock.mockResolvedValueOnce({ data: { viewer_status: null }, response: backendResponse(200) });

    const response = await GET(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(body).toEqual({ authenticated: true, status: null });
  });

  it("propagates a 404 from the backend", async () => {
    getCurrentUserMock.mockResolvedValueOnce(alice);
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await GET(new Request("http://x"), params("movie", "unknown-slug"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });
});

describe("PUT /api/{type}/{slug}/library", () => {
  it("returns 400 for an invalid type without calling apiFetch", async () => {
    const response = await PUT(putRequest({ status: "want" }), params("album", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 for malformed JSON", async () => {
    const request = new Request("http://x", { method: "PUT", body: "not json" });
    const response = await PUT(request, params("movie", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it.each([undefined, null, 42, "watching", ""])("returns 400 for an invalid status %p", async (status) => {
    const response = await PUT(putRequest({ status }), params("movie", "dune-2021"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns the updated status on a 200 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: libraryStatusOut, response: backendResponse(200) });

    const response = await PUT(putRequest({ status: "want" }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(libraryStatusOut);
  });

  it("forwards the status to putLibraryStatus with headers built from the access token", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        putLibraryStatusMock.mockResolvedValue({ data: libraryStatusOut, response: backendResponse(200) });
        const result = await call({ name: "fake-client" }, "the-token");
        expect(putLibraryStatusMock).toHaveBeenCalledWith(
          { name: "fake-client" },
          { Authorization: "Bearer the-token" },
          "movie",
          "dune-2021",
          "want",
        );
        return result;
      },
    );

    const response = await PUT(putRequest({ status: "want" }), params("movie", "dune-2021"));
    expect(response.status).toBe(200);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await PUT(putRequest({ status: "want" }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the slug doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await PUT(putRequest({ status: "want" }), params("movie", "unknown"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 422 for a backend validation failure", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(422) });

    const response = await PUT(putRequest({ status: "want" }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body).toEqual({ error: "validation_error" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await PUT(putRequest({ status: "want" }), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "set_library_failed" });
  });
});

describe("DELETE /api/{type}/{slug}/library", () => {
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

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await DELETE(new Request("http://x"), params("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the caller has no library entry for the item", async () => {
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
    expect(body).toEqual({ error: "delete_library_failed" });
  });
});
