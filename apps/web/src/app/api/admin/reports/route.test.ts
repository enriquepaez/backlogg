// @vitest-environment node
//
// Same pattern as `../stats/route.test.ts`: the Route Handler is a plain
// async function, invoked directly against the MSW mock server with
// `@/lib/auth/session` mocked to a client bound to the mock origin.
// `@/lib/env` is mocked separately so `ADMIN_API_KEY` can be toggled between
// "set" and "unset" without touching real process env vars.
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

const reportsFixture = {
  items: [
    {
      id: 1,
      reporter_id: 10,
      rating_id: 42,
      reason: "Spam",
      status: "open",
      created_at: "2026-05-25T02:03:12Z",
      resolved_at: null,
    },
  ],
  total: 1,
  page: 1,
  limit: 20,
};

function makeRequest(query = ""): Request {
  return new Request(`http://localhost/api/admin/reports${query}`);
}

afterEach(() => {
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("GET /api/admin/reports", () => {
  it("injects X-API-Key and returns the report list on 200", async () => {
    let forwardedKey: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/reports`, ({ request }) => {
        forwardedKey = request.headers.get("x-api-key");
        return HttpResponse.json(reportsFixture, { status: 200 });
      }),
    );

    const response = await GET(makeRequest());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(reportsFixture);
    expect(forwardedKey).toBe("s3cr3t");
  });

  it("forwards status/page/limit query params to the backend", async () => {
    let forwardedStatus: string | null = null;
    let forwardedPage: string | null = null;
    let forwardedLimit: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/reports`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        forwardedStatus = params.get("status");
        forwardedPage = params.get("page");
        forwardedLimit = params.get("limit");
        return HttpResponse.json(reportsFixture, { status: 200 });
      }),
    );

    await GET(makeRequest("?status=open&page=2&limit=5"));

    expect(forwardedStatus).toBe("open");
    expect(forwardedPage).toBe("2");
    expect(forwardedLimit).toBe("5");
  });

  it("omits an unrecognized status value instead of forwarding it as-is", async () => {
    let forwardedHasStatus: boolean | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/reports`, ({ request }) => {
        forwardedHasStatus = new URL(request.url).searchParams.has("status");
        return HttpResponse.json(reportsFixture, { status: 200 });
      }),
    );

    await GET(makeRequest("?status=bogus"));

    expect(forwardedHasStatus).toBe(false);
  });

  it("falls back to the default page/limit on invalid values, capping limit at MAX_LIMIT", async () => {
    let forwardedPage: string | null = null;
    let forwardedLimit: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/reports`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        forwardedPage = params.get("page");
        forwardedLimit = params.get("limit");
        return HttpResponse.json(reportsFixture, { status: 200 });
      }),
    );

    await GET(makeRequest("?page=-1&limit=9999"));

    expect(forwardedPage).toBe("1");
    expect(forwardedLimit).toBe("100");
  });

  it("returns 401 without exposing the key when the backend rejects it", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/reports`, () =>
        HttpResponse.json({ detail: "Invalid or missing X-API-Key header." }, { status: 401 }),
      ),
    );

    const response = await GET(makeRequest());
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
    expect(JSON.stringify(body)).not.toContain("s3cr3t");
  });

  it("returns 503 when the backend has no ADMIN_API_KEY configured", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/reports`, () =>
        HttpResponse.json({ detail: "Admin API key is not configured." }, { status: 503 }),
      ),
    );

    const response = await GET(makeRequest());
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
  });

  it("returns 503 without calling the backend when this app's own ADMIN_API_KEY is unset", async () => {
    envMock.ADMIN_API_KEY = undefined;
    const backendCall = vi.fn();
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/reports`, () => {
        backendCall();
        return HttpResponse.json(reportsFixture, { status: 200 });
      }),
    );

    const response = await GET(makeRequest());
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 502 on an unexpected backend status", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/reports`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const response = await GET(makeRequest());
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "admin_reports_failed" });
  });
});
