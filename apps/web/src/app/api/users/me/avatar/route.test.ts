// @vitest-environment node
//
// Same pattern as `../route.test.ts`: `apiFetch` depends on `next/headers`'
// request-scoped `cookies()`, so it's mocked here rather than exercised for
// real.
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const { POST, DELETE } = await import("./route");

beforeEach(() => {
  apiFetchMock.mockClear();
});

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function postRequest(file: File | null): Request {
  const formData = new FormData();
  if (file) {
    formData.append("file", file);
  }
  return new Request("http://localhost:3000/api/users/me/avatar", {
    method: "POST",
    body: formData,
  });
}

const pngFile = new File([new Uint8Array(4)], "avatar.png", { type: "image/png" });

describe("POST /api/users/me/avatar", () => {
  it("returns the updated profile on a 200 from the backend", async () => {
    const updated = {
      username: "alice",
      email: "alice@example.com",
      display_name: null,
      bio: null,
      avatar_url: "https://cdn.example.com/avatars/1/x.png",
      email_verified: true,
    };
    apiFetchMock.mockResolvedValueOnce({ data: updated, response: backendResponse(200) });

    const response = await POST(postRequest(pngFile));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(updated);
  });

  it("forwards the file as multipart form data to the typed client", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const backendPost = vi.fn().mockResolvedValue({
          data: { username: "alice", email: "a@example.com", display_name: null, bio: null, avatar_url: "x", email_verified: false },
          response: backendResponse(200),
        });
        const fakeClient = { POST: backendPost };

        const result = await call(fakeClient, "the-access-token");

        expect(backendPost).toHaveBeenCalledTimes(1);
        const [path, init] = backendPost.mock.calls[0] as [string, { body: FormData; headers: unknown }];
        expect(path).toBe("/v1/users/me/avatar");
        expect(init.headers).toEqual({ Authorization: "Bearer the-access-token" });
        expect(init.body).toBeInstanceOf(FormData);
        expect(init.body.get("file")).toBeInstanceOf(File);
        expect((init.body.get("file") as File).name).toBe("avatar.png");

        return result;
      },
    );

    const response = await POST(postRequest(pngFile));
    expect(response.status).toBe(200);
  });

  it("returns 400 without calling apiFetch when no file field is present", async () => {
    const response = await POST(postRequest(null));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await POST(postRequest(pngFile));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("propagates a 413 for an oversized file", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(413) });

    const response = await POST(postRequest(pngFile));
    const body = await response.json();

    expect(response.status).toBe(413);
    expect(body).toEqual({ error: "too_large" });
  });

  it("propagates a 422 for an invalid content type", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(422) });

    const response = await POST(postRequest(pngFile));
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body).toEqual({ error: "validation_error" });
  });

  it("propagates a 503 when storage isn't configured", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(503) });

    const response = await POST(postRequest(pngFile));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "storage_unavailable" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await POST(postRequest(pngFile));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "upload_avatar_failed" });
  });
});

describe("DELETE /api/users/me/avatar", () => {
  it("returns 204 on a 204 from the backend", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(204) });

    const response = await DELETE();

    expect(response.status).toBe(204);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await DELETE();
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await DELETE();
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "delete_avatar_failed" });
  });
});
