// @vitest-environment node
//
// Same pattern as `../ban/route.test.ts` (GET instead of POST, no request
// body/path suffix beyond `{username}` itself).
import { createApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MOCK_API_BASE_URL } from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const envMock = vi.hoisted(() => ({ ADMIN_API_KEY: "s3cr3t" as string | undefined }));
vi.mock("@/lib/env", () => ({
  env: {
    get ADMIN_API_KEY() {
      if (!envMock.ADMIN_API_KEY) {
        throw new Error("Missing required environment variable: ADMIN_API_KEY");
      }
      return envMock.ADMIN_API_KEY;
    },
  },
}));

const { GET } = await import("./route");

const aliceFixture = {
  username: "alice",
  display_name: "Alice A.",
  avatar_url: null,
  is_admin: false,
  is_superadmin: false,
  is_banned: false,
  created_at: "2026-05-25T02:03:12Z",
};

function makeParams(username: string) {
  return { params: Promise.resolve({ username }) };
}

afterEach(() => {
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("GET /api/admin/users/[username]", () => {
  it("injects X-API-Key and returns the user detail on 200", async () => {
    let forwardedKey: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/alice`, ({ request }) => {
        forwardedKey = request.headers.get("x-api-key");
        return HttpResponse.json(aliceFixture, { status: 200 });
      }),
    );

    const response = await GET(new Request("http://localhost"), makeParams("alice"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(aliceFixture);
    expect(forwardedKey).toBe("s3cr3t");
  });

  it("returns 401 without exposing the key when the backend rejects it", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/alice`, () =>
        HttpResponse.json({ detail: "Invalid or missing X-API-Key header." }, { status: 401 }),
      ),
    );

    const response = await GET(new Request("http://localhost"), makeParams("alice"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
    expect(JSON.stringify(body)).not.toContain("s3cr3t");
  });

  it("returns 404 when the user doesn't exist", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/ghost`, () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    const response = await GET(new Request("http://localhost"), makeParams("ghost"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 503 without calling the backend when this app's own ADMIN_API_KEY is unset", async () => {
    envMock.ADMIN_API_KEY = undefined;
    const backendCall = vi.fn();
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/alice`, () => {
        backendCall();
        return HttpResponse.json(aliceFixture, { status: 200 });
      }),
    );

    const response = await GET(new Request("http://localhost"), makeParams("alice"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 503 when the backend has no ADMIN_API_KEY configured", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/alice`, () =>
        HttpResponse.json({ detail: "Admin API key is not configured." }, { status: 503 }),
      ),
    );

    const response = await GET(new Request("http://localhost"), makeParams("alice"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
  });

  it("returns 502 on an unexpected backend status", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/alice`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const response = await GET(new Request("http://localhost"), makeParams("alice"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "admin_user_detail_failed" });
  });
});
