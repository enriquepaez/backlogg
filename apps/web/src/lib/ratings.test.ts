import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@backlogg/api-client";

import { deleteRating, likeReview, listRatings, putRating, unlikeReview } from "./ratings";

/**
 * `putRating`/`deleteRating`/`listRatings` only dispatch to the right
 * per-type templated operation and forward their arguments through — same
 * spirit as `catalog.test.ts` would cover for `getItemDetail`'s per-type
 * switch. A minimal fake `ApiClient` (just the three methods these helpers
 * touch) is enough; the real per-type path strings/response shapes are
 * already enforced by `packages/api-client`'s generated types at compile
 * time.
 */
function fakeClient(): ApiClient {
  return {
    PUT: vi.fn().mockResolvedValue({ data: { id: 1 }, response: new Response(null, { status: 200 }) }),
    POST: vi.fn().mockResolvedValue({ response: new Response(null, { status: 204 }) }),
    DELETE: vi.fn().mockResolvedValue({ response: new Response(null, { status: 204 }) }),
    GET: vi.fn().mockResolvedValue({ data: { items: [] }, response: new Response(null, { status: 200 }) }),
  } as unknown as ApiClient;
}

describe("putRating", () => {
  it.each([
    ["movie", "/v1/movies/{slug}/rating"],
    ["series", "/v1/series/{slug}/rating"],
    ["book", "/v1/books/{slug}/rating"],
    ["game", "/v1/games/{slug}/rating"],
  ] as const)("dispatches %s to %s", async (type, path) => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };
    const body = { score: 4, review_text: "Great" };

    await putRating(client, headers, type, "some-slug", body);

    expect(client.PUT).toHaveBeenCalledWith(path, {
      params: { path: { slug: "some-slug" } },
      body,
      headers,
    });
  });
});

describe("deleteRating", () => {
  it.each([
    ["movie", "/v1/movies/{slug}/rating"],
    ["series", "/v1/series/{slug}/rating"],
    ["book", "/v1/books/{slug}/rating"],
    ["game", "/v1/games/{slug}/rating"],
  ] as const)("dispatches %s to %s", async (type, path) => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    await deleteRating(client, headers, type, "some-slug");

    expect(client.DELETE).toHaveBeenCalledWith(path, {
      params: { path: { slug: "some-slug" } },
      headers,
    });
  });
});

describe("listRatings", () => {
  it.each([
    ["movie", "/v1/movies/{slug}/ratings"],
    ["series", "/v1/series/{slug}/ratings"],
    ["book", "/v1/books/{slug}/ratings"],
    ["game", "/v1/games/{slug}/ratings"],
  ] as const)("dispatches %s to %s", async (type, path) => {
    const client = fakeClient();

    await listRatings(client, type, "some-slug", { page: 1, limit: 100 });

    expect(client.GET).toHaveBeenCalledWith(path, {
      params: { path: { slug: "some-slug" }, query: { page: 1, limit: 100 } },
      headers: {},
    });
  });

  it("forwards the caller's Authorization header when provided, so the backend can resolve liked_by_viewer", async () => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer viewer-token" };

    await listRatings(client, "movie", "some-slug", { page: 1, limit: 10 }, headers);

    expect(client.GET).toHaveBeenCalledWith("/v1/movies/{slug}/ratings", {
      params: { path: { slug: "some-slug" }, query: { page: 1, limit: 10 } },
      headers,
    });
  });
});

describe("likeReview", () => {
  it("POSTs to /v1/ratings/{rating_id}/like with the rating id and headers", async () => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    await likeReview(client, headers, 42);

    expect(client.POST).toHaveBeenCalledWith("/v1/ratings/{rating_id}/like", {
      params: { path: { rating_id: 42 } },
      headers,
    });
  });
});

describe("unlikeReview", () => {
  it("DELETEs /v1/ratings/{rating_id}/like with the rating id and headers", async () => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    await unlikeReview(client, headers, 42);

    expect(client.DELETE).toHaveBeenCalledWith("/v1/ratings/{rating_id}/like", {
      params: { path: { rating_id: 42 } },
      headers,
    });
  });
});
