// @vitest-environment node
//
// Same pattern as `../../route.test.ts`/`../../../stats/route.test.ts`.
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

const { POST } = await import("./route");

const resolvedFixture = {
  id: 1,
  reporter_id: 10,
  rating_id: 42,
  reason: "Spam",
  status: "resolved",
  created_at: "2026-05-25T02:03:12Z",
  resolved_at: "2026-05-26T02:03:12Z",
};

function makeParams(id: string) {
  return { params: Promise.resolve({ id }) };
}

afterEach(() => {
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("POST /api/admin/reports/[id]/resolve", () => {
  it("injects X-API-Key and returns the resolved report on 200", async () => {
    let forwardedKey: string | null = null;
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/reports/1/resolve`, ({ request }) => {
        forwardedKey = request.headers.get("x-api-key");
        return HttpResponse.json(resolvedFixture, { status: 200 });
      }),
    );

    const response = await POST(new Request("http://localhost"), makeParams("1"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(resolvedFixture);
    expect(forwardedKey).toBe("s3cr3t");
  });

  it("returns 400 without calling the backend for a non-numeric id", async () => {
    const backendCall = vi.fn();
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/reports/:id/resolve`, () => {
        backendCall();
        return HttpResponse.json(resolvedFixture, { status: 200 });
      }),
    );

    const response = await POST(new Request("http://localhost"), makeParams("not-a-number"));
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body).toEqual({ error: "invalid_id" });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 401 without exposing the key when the backend rejects it", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/reports/1/resolve`, () =>
        HttpResponse.json({ detail: "Invalid or missing X-API-Key header." }, { status: 401 }),
      ),
    );

    const response = await POST(new Request("http://localhost"), makeParams("1"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
    expect(JSON.stringify(body)).not.toContain("s3cr3t");
  });

  it("returns 404 when the report doesn't exist", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/reports/999/resolve`, () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    const response = await POST(new Request("http://localhost"), makeParams("999"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 503 when the backend has no ADMIN_API_KEY configured", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/reports/1/resolve`, () =>
        HttpResponse.json({ detail: "Admin API key is not configured." }, { status: 503 }),
      ),
    );

    const response = await POST(new Request("http://localhost"), makeParams("1"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
  });

  it("returns 503 without calling the backend when this app's own ADMIN_API_KEY is unset", async () => {
    envMock.ADMIN_API_KEY = undefined;
    const backendCall = vi.fn();
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/reports/1/resolve`, () => {
        backendCall();
        return HttpResponse.json(resolvedFixture, { status: 200 });
      }),
    );

    const response = await POST(new Request("http://localhost"), makeParams("1"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 502 on an unexpected backend status", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/reports/1/resolve`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const response = await POST(new Request("http://localhost"), makeParams("1"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "resolve_report_failed" });
  });
});
