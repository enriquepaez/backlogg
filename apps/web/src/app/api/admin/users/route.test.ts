// @vitest-environment node
//
// Same pattern as `../reports/route.test.ts`: the Route Handler is a plain
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

const usersFixture = {
  items: [
    {
      username: "alice",
      display_name: "Alice",
      avatar_url: null,
      is_admin: false,
      is_superadmin: false,
      is_banned: false,
      created_at: "2026-05-25T02:03:12Z",
    },
  ],
  total: 1,
  page: 1,
  limit: 20,
};

function makeRequest(query = ""): Request {
  return new Request(`http://localhost/api/admin/users${query}`);
}

afterEach(() => {
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("GET /api/admin/users", () => {
  it("injects X-API-Key and returns the user list on 200", async () => {
    let forwardedKey: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, ({ request }) => {
        forwardedKey = request.headers.get("x-api-key");
        return HttpResponse.json(usersFixture, { status: 200 });
      }),
    );

    const response = await GET(makeRequest());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(usersFixture);
    expect(forwardedKey).toBe("s3cr3t");
  });

  it("forwards is_banned/is_admin/search/page/limit query params to the backend", async () => {
    let forwardedIsBanned: string | null = null;
    let forwardedIsAdmin: string | null = null;
    let forwardedSearch: string | null = null;
    let forwardedPage: string | null = null;
    let forwardedLimit: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        forwardedIsBanned = params.get("is_banned");
        forwardedIsAdmin = params.get("is_admin");
        forwardedSearch = params.get("search");
        forwardedPage = params.get("page");
        forwardedLimit = params.get("limit");
        return HttpResponse.json(usersFixture, { status: 200 });
      }),
    );

    await GET(makeRequest("?is_banned=true&is_admin=false&search=ali&page=2&limit=5"));

    expect(forwardedIsBanned).toBe("true");
    expect(forwardedIsAdmin).toBe("false");
    expect(forwardedSearch).toBe("ali");
    expect(forwardedPage).toBe("2");
    expect(forwardedLimit).toBe("5");
  });

  it("trims search before forwarding it to the backend", async () => {
    let forwardedSearch: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, ({ request }) => {
        forwardedSearch = new URL(request.url).searchParams.get("search");
        return HttpResponse.json(usersFixture, { status: 200 });
      }),
    );

    await GET(makeRequest("?search=%20%20alice%20%20"));

    expect(forwardedSearch).toBe("alice");
  });

  it("omits search entirely when it's empty/whitespace-only after trimming", async () => {
    let forwardedHasSearch: boolean | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, ({ request }) => {
        forwardedHasSearch = new URL(request.url).searchParams.has("search");
        return HttpResponse.json(usersFixture, { status: 200 });
      }),
    );

    await GET(makeRequest("?search=%20%20%20"));

    expect(forwardedHasSearch).toBe(false);
  });

  it("omits search when the query param is absent", async () => {
    let forwardedHasSearch: boolean | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, ({ request }) => {
        forwardedHasSearch = new URL(request.url).searchParams.has("search");
        return HttpResponse.json(usersFixture, { status: 200 });
      }),
    );

    await GET(makeRequest());

    expect(forwardedHasSearch).toBe(false);
  });

  it("omits an unrecognized is_banned/is_admin value instead of forwarding it as-is", async () => {
    let forwardedHasIsBanned: boolean | null = null;
    let forwardedHasIsAdmin: boolean | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        forwardedHasIsBanned = params.has("is_banned");
        forwardedHasIsAdmin = params.has("is_admin");
        return HttpResponse.json(usersFixture, { status: 200 });
      }),
    );

    await GET(makeRequest("?is_banned=bogus&is_admin=1"));

    expect(forwardedHasIsBanned).toBe(false);
    expect(forwardedHasIsAdmin).toBe(false);
  });

  it("falls back to the default page/limit on invalid values, capping limit at MAX_LIMIT", async () => {
    let forwardedPage: string | null = null;
    let forwardedLimit: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        forwardedPage = params.get("page");
        forwardedLimit = params.get("limit");
        return HttpResponse.json(usersFixture, { status: 200 });
      }),
    );

    await GET(makeRequest("?page=-1&limit=9999"));

    expect(forwardedPage).toBe("1");
    expect(forwardedLimit).toBe("100");
  });

  it("returns 401 without exposing the key when the backend rejects it", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, () =>
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
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, () =>
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
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, () => {
        backendCall();
        return HttpResponse.json(usersFixture, { status: 200 });
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
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const response = await GET(makeRequest());
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "admin_users_failed" });
  });
});
