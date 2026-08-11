// @vitest-environment node
//
// Exercises the `/api/auth/register` Route Handler directly (it's a plain
// async function receiving/returning `Request`/`NextResponse`, so it can be
// invoked without a running Next server) against the MSW mock server — same
// pattern as `src/lib/search.test.ts`: `@/lib/auth/session` is mocked to a
// client bound to the mock origin so this runs under plain Vitest without
// pulling in `server-only`/`API_INTERNAL_URL`.
import { createApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { MOCK_API_BASE_URL } from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const { POST } = await import("./route");

function registerRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const validBody = {
  username: "valid_user-1",
  email: "user@example.com",
  password: "longenough1",
  display_name: "Jane",
};

describe("POST /api/auth/register", () => {
  it("proxies a 201 from the backend, echoing username/email/password/display_name", async () => {
    let forwardedBody: unknown;
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/register`, async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(
          {
            username: validBody.username,
            email: validBody.email,
            display_name: validBody.display_name,
            bio: null,
            avatar_url: null,
            email_verified: false,
          },
          { status: 201 },
        );
      }),
    );

    const response = await POST(registerRequest(validBody));

    expect(response.status).toBe(201);
    expect(forwardedBody).toEqual(validBody);
  });

  it("propagates a 409 when the username/email is already in use", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/register`, () =>
        HttpResponse.json({ detail: "Username or email already in use" }, { status: 409 }),
      ),
    );

    const response = await POST(registerRequest(validBody));
    expect(response.status).toBe(409);
  });

  it("propagates a 422 for a backend validation failure", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/register`, () =>
        HttpResponse.json(
          { detail: [{ loc: ["body", "password"], msg: "too short", type: "value_error" }] },
          { status: 422 },
        ),
      ),
    );

    const response = await POST(registerRequest(validBody));
    expect(response.status).toBe(422);
  });

  it("propagates a 429 with its Retry-After header", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/register`, () =>
        HttpResponse.json({ detail: "Too Many Requests" }, { status: 429, headers: { "Retry-After": "45" } }),
      ),
    );

    const response = await POST(registerRequest(validBody));
    expect(response.status).toBe(429);
    expect(response.headers.get("Retry-After")).toBe("45");
  });

  it("returns 400 without calling the backend for a malformed body", async () => {
    const backendCall = vi.fn();
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/auth/register`, () => {
        backendCall();
        return HttpResponse.json({}, { status: 201 });
      }),
    );

    const response = await POST(registerRequest({ username: "valid_user" }));
    expect(response.status).toBe(400);
    expect(backendCall).not.toHaveBeenCalled();
  });
});
