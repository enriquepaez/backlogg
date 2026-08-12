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

function forgotRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/auth/password/forgot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/auth/password/forgot", () => {
  it("proxies a 202 from the backend, forwarding the email in the body", async () => {
    let forwardedBody: unknown;
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/forgot`, async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ detail: "If the email exists, a link was sent" }, { status: 202 });
      }),
    );

    const response = await POST(forgotRequest({ email: "user@example.com" }));
    const body = await response.json();

    expect(response.status).toBe(202);
    expect(body).toEqual({ ok: true });
    expect(forwardedBody).toEqual({ email: "user@example.com" });
  });

  it("still answers 202 for an email that doesn't exist — no enumeration", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/forgot`, () =>
        HttpResponse.json({ detail: "If the email exists, a link was sent" }, { status: 202 }),
      ),
    );

    const response = await POST(forgotRequest({ email: "nobody@example.com" }));
    expect(response.status).toBe(202);
  });

  it("propagates a 422 for a backend validation failure", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/forgot`, () =>
        HttpResponse.json(
          { detail: [{ loc: ["body", "email"], msg: "invalid email", type: "value_error" }] },
          { status: 422 },
        ),
      ),
    );

    const response = await POST(forgotRequest({ email: "not-an-email" }));
    expect(response.status).toBe(422);
  });

  it("returns 400 without calling the backend when the email is missing", async () => {
    const backendCall = vi.fn();
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/password/forgot`, () => {
        backendCall();
        return HttpResponse.json({ detail: "ok" }, { status: 202 });
      }),
    );

    const response = await POST(forgotRequest({}));

    expect(response.status).toBe(400);
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 400 for a malformed JSON body", async () => {
    const request = new Request("http://localhost:3000/api/auth/password/forgot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json",
    });

    const response = await POST(request);
    expect(response.status).toBe(400);
  });
});
