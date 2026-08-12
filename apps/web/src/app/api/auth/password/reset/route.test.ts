// @vitest-environment node
//
// Same pattern as `src/app/api/auth/verify/confirm/route.test.ts`.
import { createApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { MOCK_API_BASE_URL } from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const { POST } = await import("./route");

function resetRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/auth/password/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/auth/password/reset", () => {
  it("proxies a 200 from the backend, forwarding token and new_password", async () => {
    let forwardedBody: unknown;
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/reset`, async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ detail: "Password changed" });
      }),
    );

    const response = await POST(resetRequest({ token: "a-valid-token", new_password: "longenough1" }));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ ok: true });
    expect(forwardedBody).toEqual({ token: "a-valid-token", new_password: "longenough1" });
  });

  it("propagates a 400 for an invalid/expired/already-used token", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/reset`, () =>
        HttpResponse.json({ detail: "Invalid or expired token" }, { status: 400 }),
      ),
    );

    const response = await POST(resetRequest({ token: "not-a-real-token", new_password: "longenough1" }));
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body).toEqual({ error: "invalid_token" });
  });

  it("propagates a 422 for a backend validation failure", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/reset`, () =>
        HttpResponse.json(
          { detail: [{ loc: ["body", "new_password"], msg: "too short", type: "value_error" }] },
          { status: 422 },
        ),
      ),
    );

    const response = await POST(resetRequest({ token: "a-valid-token", new_password: "short" }));
    expect(response.status).toBe(422);
  });

  it("returns 400 without calling the backend when the token is missing", async () => {
    const backendCall = vi.fn();
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/reset`, () => {
        backendCall();
        return HttpResponse.json({ detail: "Password changed" });
      }),
    );

    const response = await POST(resetRequest({ new_password: "longenough1" }));

    expect(response.status).toBe(400);
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 400 without calling the backend when new_password is missing", async () => {
    const backendCall = vi.fn();
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/reset`, () => {
        backendCall();
        return HttpResponse.json({ detail: "Password changed" });
      }),
    );

    const response = await POST(resetRequest({ token: "a-valid-token" }));

    expect(response.status).toBe(400);
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 400 for a malformed JSON body", async () => {
    const request = new Request("http://localhost:3000/api/auth/password/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json",
    });

    const response = await POST(request);
    expect(response.status).toBe(400);
  });
});
