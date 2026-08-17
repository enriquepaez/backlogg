// @vitest-environment node
//
// Same pattern as `../../users/route.test.ts`: the Route Handler is a plain
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

const { PATCH } = await import("./route");

const editOutFixture = {
  type: "movie",
  slug: "dune-2021",
  title: "Dune",
  poster_url: "https://example.com/dune.jpg",
  release_date: "2021-10-22",
  first_air_date: null,
  first_publish_date: null,
  genres: ["Science Fiction"],
  locked_fields: ["title"],
};

function makeRequest(body: unknown): Request {
  return new Request("http://localhost/api/admin/movie/dune-2021", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function routeParams(type: string, slug: string) {
  return { params: Promise.resolve({ type, slug }) };
}

afterEach(() => {
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("PATCH /api/admin/[type]/[slug]", () => {
  it("injects X-API-Key and forwards a clean CatalogEditIn body", async () => {
    let forwardedKey: string | null = null;
    let forwardedBody: unknown = null;
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, async ({ request }) => {
        forwardedKey = request.headers.get("x-api-key");
        forwardedBody = await request.json();
        return HttpResponse.json(editOutFixture, { status: 200 });
      }),
    );

    const response = await PATCH(
      makeRequest({ title: "Dune", genres: ["Science Fiction"], extra_ignored_key: "nope" }),
      routeParams("movie", "dune-2021"),
    );
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(editOutFixture);
    expect(forwardedKey).toBe("s3cr3t");
    // Unknown keys are dropped, never forwarded to the backend.
    expect(forwardedBody).toEqual({ title: "Dune", genres: ["Science Fiction"] });
  });

  it("forwards an empty body as-is (the fetchAdminCatalogItem 'peek' case)", async () => {
    let forwardedBody: unknown = "not-called";
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(editOutFixture, { status: 200 });
      }),
    );

    await PATCH(makeRequest({}), routeParams("movie", "dune-2021"));

    expect(forwardedBody).toEqual({});
  });

  it("forwards unlock_fields alongside edited fields", async () => {
    let forwardedBody: unknown = null;
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(editOutFixture, { status: 200 });
      }),
    );

    await PATCH(
      makeRequest({ poster_url: "https://example.com/new.jpg", unlock_fields: ["title"] }),
      routeParams("movie", "dune-2021"),
    );

    expect(forwardedBody).toEqual({
      poster_url: "https://example.com/new.jpg",
      unlock_fields: ["title"],
    });
  });

  it("returns 400 for an unrecognized type segment without calling the backend", async () => {
    const backendCall = vi.fn();
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, () => {
        backendCall();
        return HttpResponse.json(editOutFixture, { status: 200 });
      }),
    );

    const response = await PATCH(makeRequest({}), routeParams("album", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body).toEqual({ error: "invalid_type" });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 400 for a malformed JSON body", async () => {
    const request = new Request("http://localhost/api/admin/movie/dune-2021", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: "{not json",
    });

    const response = await PATCH(request, routeParams("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body).toEqual({ error: "invalid_body" });
  });

  it("returns 400 when a known key has the wrong type", async () => {
    const response = await PATCH(makeRequest({ genres: "not-an-array" }), routeParams("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(400);
    expect(body).toEqual({ error: "invalid_body" });
  });

  it("returns 401 when the backend rejects the key", async () => {
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, () =>
        HttpResponse.json({ detail: "Invalid or missing X-API-Key header." }, { status: 401 }),
      ),
    );

    const response = await PATCH(makeRequest({ title: "Dune" }), routeParams("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
    expect(JSON.stringify(body)).not.toContain("s3cr3t");
  });

  it("returns 404 for an unknown slug", async () => {
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, () =>
        HttpResponse.json({ detail: "Item not found" }, { status: 404 }),
      ),
    );

    const response = await PATCH(makeRequest({ title: "Dune" }), routeParams("movie", "missing-slug"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 422 for a non-editable field or an empty title", async () => {
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, () =>
        HttpResponse.json({ detail: "title cannot be empty" }, { status: 422 }),
      ),
    );

    const response = await PATCH(makeRequest({ title: "   " }), routeParams("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(422);
    expect(body).toEqual({ error: "validation_error" });
  });

  it("returns 503 when the backend has no ADMIN_API_KEY configured", async () => {
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, () =>
        HttpResponse.json({ detail: "Admin API key is not configured." }, { status: 503 }),
      ),
    );

    const response = await PATCH(makeRequest({ title: "Dune" }), routeParams("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
  });

  it("returns 503 without calling the backend when this app's own ADMIN_API_KEY is unset", async () => {
    envMock.ADMIN_API_KEY = undefined;
    const backendCall = vi.fn();
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, () => {
        backendCall();
        return HttpResponse.json(editOutFixture, { status: 200 });
      }),
    );

    const response = await PATCH(makeRequest({ title: "Dune" }), routeParams("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 502 on an unexpected backend status", async () => {
    server.use(
      http.patch(`${MOCK_API_BASE_URL}/v1/admin/:type/:slug`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const response = await PATCH(makeRequest({ title: "Dune" }), routeParams("movie", "dune-2021"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "admin_catalog_edit_failed" });
  });
});
