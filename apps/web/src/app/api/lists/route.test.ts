// @vitest-environment node
//
// Same pattern as `../users/me/route.test.ts`: `apiFetch` is mocked so this
// file only exercises the route's own body validation/branching, not
// `apiFetch`'s refresh dance (covered by its own tests) or `createList`'s
// dispatch (a one-line pass-through, no test needed of its own — same
// reasoning as `follows.test.ts`'s doc comment for `followUser`/`unfollowUser`).
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const createListMock = vi.fn();
vi.mock("@/lib/lists", () => ({
  createList: (...args: unknown[]) => createListMock(...args),
}));

const { POST } = await import("./route");

beforeEach(() => {
  apiFetchMock.mockClear();
  createListMock.mockClear();
});

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function postRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/lists", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const createdList = {
  slug: "best-sci-fi",
  title: "Best sci-fi",
  description: "My favorites",
  is_public: true,
  item_count: 0,
  created_at: "2026-05-20T10:00:00Z",
  updated_at: "2026-05-20T10:00:00Z",
  items: [],
};

describe("POST /api/lists", () => {
  it("returns the created list on a 201 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: createdList, response: backendResponse(201) });

    const response = await POST(
      postRequest({ title: "Best sci-fi", description: "My favorites", is_public: true }),
    );
    const body = await response.json();

    expect(response.status).toBe(201);
    expect(body).toEqual(createdList);
  });

  it("forwards title/description/is_public as ListCreate to the typed client, defaulting description to null and is_public to true", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        createListMock.mockResolvedValue({ data: createdList, response: backendResponse(201) });
        const result = await call({ name: "fake-client" }, "the-access-token");

        expect(createListMock).toHaveBeenCalledWith(
          { name: "fake-client" },
          { Authorization: "Bearer the-access-token" },
          { title: "Best sci-fi", description: null, is_public: true },
        );
        return result;
      },
    );

    const response = await POST(postRequest({ title: "Best sci-fi" }));
    expect(response.status).toBe(201);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await POST(postRequest({ title: "Best sci-fi" }));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("propagates a 422 for a backend validation failure", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(422) });

    const response = await POST(postRequest({ title: "Best sci-fi" }));
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body).toEqual({ error: "validation_error" });
  });

  it("returns 400 without calling apiFetch for a malformed JSON body", async () => {
    const request = new Request("http://localhost:3000/api/lists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json",
    });

    const response = await POST(request);

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 without calling apiFetch for a missing/empty title", async () => {
    const response = await POST(postRequest({ title: "   " }));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 without calling apiFetch when is_public has the wrong type", async () => {
    const response = await POST(postRequest({ title: "Best sci-fi", is_public: "yes" }));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await POST(postRequest({ title: "Best sci-fi" }));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "create_list_failed" });
  });
});
