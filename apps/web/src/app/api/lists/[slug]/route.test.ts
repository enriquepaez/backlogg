// @vitest-environment node
//
// Same pattern as `../../users/me/route.test.ts` and
// `../../users/[username]/follow/route.test.ts`: `apiFetch` and `@/lib/lists`
// are mocked so this file only exercises the route's own body
// validation/branching, not `apiFetch`'s refresh dance or `updateList`/
// `deleteList`'s dispatch (one-line pass-throughs, no test needed of their
// own).
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const updateListMock = vi.fn();
const deleteListMock = vi.fn();
vi.mock("@/lib/lists", () => ({
  updateList: (...args: unknown[]) => updateListMock(...args),
  deleteList: (...args: unknown[]) => deleteListMock(...args),
}));

const { PATCH, DELETE } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(slug: string) {
  return { params: Promise.resolve({ slug }) };
}

function patchRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/lists/best-sci-fi", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  apiFetchMock.mockClear();
  updateListMock.mockClear();
  deleteListMock.mockClear();
});

const updatedList = {
  slug: "best-sci-fi",
  title: "Best sci-fi ever",
  description: null,
  is_public: false,
  item_count: 2,
  created_at: "2026-05-20T10:00:00Z",
  updated_at: "2026-05-25T18:04:11Z",
  items: [],
};

describe("PATCH /api/lists/{slug}", () => {
  it("returns the updated list on a 200 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: updatedList, response: backendResponse(200) });

    const response = await PATCH(
      patchRequest({ title: "Best sci-fi ever", description: null, is_public: false }),
      params("best-sci-fi"),
    );
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(updatedList);
  });

  it("forwards title/description/is_public as ListUpdate to the typed client", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        updateListMock.mockResolvedValue({ data: updatedList, response: backendResponse(200) });
        const result = await call({ name: "fake-client" }, "the-access-token");

        expect(updateListMock).toHaveBeenCalledWith(
          { name: "fake-client" },
          { Authorization: "Bearer the-access-token" },
          "best-sci-fi",
          { title: "Best sci-fi ever", description: null, is_public: false },
        );
        return result;
      },
    );

    const response = await PATCH(
      patchRequest({ title: "Best sci-fi ever", description: null, is_public: false }),
      params("best-sci-fi"),
    );
    expect(response.status).toBe(200);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await PATCH(
      patchRequest({ title: "Best sci-fi ever", description: null, is_public: false }),
      params("best-sci-fi"),
    );
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 403 when the caller isn't the owner", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(403) });

    const response = await PATCH(
      patchRequest({ title: "Best sci-fi ever", description: null, is_public: false }),
      params("someone-elses-list"),
    );
    const body = await response.json();

    expect(response.status).toBe(403);
    expect(body).toEqual({ error: "forbidden" });
  });

  it("returns 404 when the list doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await PATCH(
      patchRequest({ title: "Best sci-fi ever", description: null, is_public: false }),
      params("ghost-list"),
    );
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 400 without calling apiFetch for a missing/empty title", async () => {
    const response = await PATCH(
      patchRequest({ title: "  ", description: null, is_public: false }),
      params("best-sci-fi"),
    );

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 without calling apiFetch when is_public is missing", async () => {
    const response = await PATCH(
      patchRequest({ title: "Best sci-fi ever", description: null }),
      params("best-sci-fi"),
    );

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await PATCH(
      patchRequest({ title: "Best sci-fi ever", description: null, is_public: false }),
      params("best-sci-fi"),
    );
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "update_list_failed" });
  });
});

describe("DELETE /api/lists/{slug}", () => {
  it("returns 204 on a 204 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(204) });

    const response = await DELETE(new Request("http://x"), params("best-sci-fi"));

    expect(response.status).toBe(204);
  });

  it("forwards the slug to deleteList with headers built from the access token", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        deleteListMock.mockResolvedValue({ response: backendResponse(204) });
        const result = await call({ name: "fake-client" }, "the-token");

        expect(deleteListMock).toHaveBeenCalledWith(
          { name: "fake-client" },
          { Authorization: "Bearer the-token" },
          "best-sci-fi",
        );
        return result;
      },
    );

    const response = await DELETE(new Request("http://x"), params("best-sci-fi"));
    expect(response.status).toBe(204);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await DELETE(new Request("http://x"), params("best-sci-fi"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 403 when the caller isn't the owner", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(403) });

    const response = await DELETE(new Request("http://x"), params("someone-elses-list"));
    const body = await response.json();

    expect(response.status).toBe(403);
    expect(body).toEqual({ error: "forbidden" });
  });

  it("returns 404 when the list doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await DELETE(new Request("http://x"), params("ghost-list"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await DELETE(new Request("http://x"), params("best-sci-fi"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "delete_list_failed" });
  });
});
