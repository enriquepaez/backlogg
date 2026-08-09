// @vitest-environment node
//
// Demonstrates the MSW pattern (acceptance criterion for FE-7): the typed
// `@backlogg/api-client` talks to a plain HTTP URL, and MSW's node server
// (registered globally in `src/test/setup.ts`) intercepts the request before
// it ever hits the network — no backend process required. Runs under the
// `node` environment (via the pragma above) since it exercises fetch/HTTP
// only, no DOM.
import { createApiClient } from "@backlogg/api-client";
import { describe, expect, it } from "vitest";

import {
  MOCK_API_BASE_URL,
  duneFixture,
  movieListFixture,
} from "./handlers";
import { server } from "./server";
import { http, HttpResponse } from "msw";

describe("createApiClient against a mocked /v1", () => {
  it("parses a GET /v1/movies list response", async () => {
    const api = createApiClient(MOCK_API_BASE_URL);

    const { data, error, response } = await api.GET("/v1/movies", {
      params: { query: { page: 1, limit: 20 } },
    });

    expect(response.status).toBe(200);
    expect(error).toBeUndefined();
    expect(data).toEqual(movieListFixture);
    expect(data?.items[0]?.slug).toBe("dune-2021");
  });

  it("parses a GET /v1/movies/{slug} detail response", async () => {
    const api = createApiClient(MOCK_API_BASE_URL);

    const { data, response } = await api.GET("/v1/movies/{slug}", {
      params: { path: { slug: duneFixture.slug } },
    });

    expect(response.status).toBe(200);
    expect(data).toEqual(duneFixture);
  });

  it("surfaces a 404 for an unknown slug", async () => {
    const api = createApiClient(MOCK_API_BASE_URL);

    const { response } = await api.GET("/v1/movies/{slug}", {
      params: { path: { slug: "does-not-exist" } },
    });

    expect(response.status).toBe(404);
  });

  it("supports per-test overrides via server.use()", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/movies`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, limit: 20 }),
      ),
    );

    const api = createApiClient(MOCK_API_BASE_URL);
    const { data } = await api.GET("/v1/movies", {});

    expect(data?.total).toBe(0);
    expect(data?.items).toEqual([]);
  });
});
