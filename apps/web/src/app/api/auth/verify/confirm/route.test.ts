// @vitest-environment node
//
// Same pattern as `src/app/api/auth/register/route.test.ts`: the Route
// Handler is a plain async function receiving/returning `Request`/
// `NextResponse`, invoked directly against the MSW mock server with
// `@/lib/auth/session` mocked to a client bound to the mock origin.
import { createApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { MOCK_API_BASE_URL } from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const { POST } = await import("./route");

function confirmRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/auth/verify/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/auth/verify/confirm", () => {
  it("proxies a 200 from the backend, forwarding the token in the body", async () => {
    let forwardedBody: unknown;
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/verify/confirm`, async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ detail: "Email verified" });
      }),
    );

    const response = await POST(confirmRequest({ token: "a-valid-token" }));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ ok: true });
    expect(forwardedBody).toEqual({ token: "a-valid-token" });
  });

  it("propagates a 400 for an invalid/expired/already-used token", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/verify/confirm`, () =>
        HttpResponse.json({ detail: "Invalid or expired token" }, { status: 400 }),
      ),
    );

    const response = await POST(confirmRequest({ token: "not-a-real-token" }));
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body).toEqual({ error: "invalid_token" });
  });

  it("returns 400 without calling the backend when the token is missing", async () => {
    const backendCall = vi.fn();
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/verify/confirm`, () => {
        backendCall();
        return HttpResponse.json({ detail: "Email verified" });
      }),
    );

    const response = await POST(confirmRequest({}));

    expect(response.status).toBe(400);
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 400 for a malformed JSON body", async () => {
    const request = new Request("http://localhost:3000/api/auth/verify/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json",
    });

    const response = await POST(request);
    expect(response.status).toBe(400);
  });
});
