// @vitest-environment node
//
// Same pattern as `../../auth/password/forgot/route.test.ts`: the Route
// Handler is a plain async function, invoked directly against the MSW mock
// server with `@/lib/auth/session` mocked to a client bound to the mock
// origin. `@/lib/env` is mocked separately per-test so `ADMIN_API_KEY` can be
// toggled between "set" and "unset" without touching real process env vars.
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

const statsFixture = {
  movies: { count: 847, last_synced_at: "2026-05-25T02:03:12Z" },
  series: { count: 312, last_synced_at: "2026-05-25T02:04:01Z" },
  books: { count: 520, last_synced_at: "2026-05-25T02:05:44Z" },
  games: { count: 198, last_synced_at: "2026-05-25T02:06:33Z" },
};

afterEach(() => {
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("GET /api/admin/stats", () => {
  it("injects X-API-Key and returns the stats on 200", async () => {
    let forwardedKey: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/stats`, ({ request }) => {
        forwardedKey = request.headers.get("x-api-key");
        return HttpResponse.json(statsFixture, { status: 200 });
      }),
    );

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(statsFixture);
    expect(forwardedKey).toBe("s3cr3t");
  });

  it("returns 401 without exposing the key when the backend rejects it", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/stats`, () =>
        HttpResponse.json({ detail: "Invalid or missing X-API-Key header." }, { status: 401 }),
      ),
    );

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
    expect(JSON.stringify(body)).not.toContain("s3cr3t");
  });

  it("returns 503 when the backend has no ADMIN_API_KEY configured", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/stats`, () =>
        HttpResponse.json({ detail: "Admin API key is not configured." }, { status: 503 }),
      ),
    );

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
  });

  it("returns 503 without calling the backend when this app's own ADMIN_API_KEY is unset", async () => {
    envMock.ADMIN_API_KEY = undefined;
    const backendCall = vi.fn();
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/stats`, () => {
        backendCall();
        return HttpResponse.json(statsFixture, { status: 200 });
      }),
    );

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 502 on an unexpected backend status", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/stats`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "admin_stats_failed" });
  });
});
