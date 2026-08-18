import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@backlogg/api-client";

import { deleteLog, getUserLog, listLog, postLog } from "./activity-log";

/**
 * `postLog`/`listLog` only dispatch to the right per-type templated
 * operation and forward their arguments through — same spirit/fake-client
 * shape as `ratings.test.ts`. `deleteLog`/`getUserLog` aren't per-type
 * (`/v1/log/{log_id}` takes the log's own numeric id, `/v1/users/{username}/log`
 * takes a username, docs/api.md), so they need no such switch.
 */
function fakeClient(): ApiClient {
  return {
    POST: vi.fn().mockResolvedValue({ data: { id: 1 }, response: new Response(null, { status: 201 }) }),
    GET: vi.fn().mockResolvedValue({ data: { items: [] }, response: new Response(null, { status: 200 }) }),
    DELETE: vi.fn().mockResolvedValue({ response: new Response(null, { status: 204 }) }),
  } as unknown as ApiClient;
}

describe("postLog", () => {
  it.each([
    ["movie", "/v1/movies/{slug}/log"],
    ["series", "/v1/series/{slug}/log"],
    ["book", "/v1/books/{slug}/log"],
    ["game", "/v1/games/{slug}/log"],
  ] as const)("dispatches %s to %s", async (type, path) => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };
    const body = { logged_on: "2026-01-01", rewatch: true, note: "Great rewatch" };

    await postLog(client, headers, type, "some-slug", body);

    expect(client.POST).toHaveBeenCalledWith(path, {
      params: { path: { slug: "some-slug" } },
      body,
      headers,
    });
  });
});

describe("listLog", () => {
  it.each([
    ["movie", "/v1/movies/{slug}/log"],
    ["series", "/v1/series/{slug}/log"],
    ["book", "/v1/books/{slug}/log"],
    ["game", "/v1/games/{slug}/log"],
  ] as const)("dispatches %s to %s", async (type, path) => {
    const client = fakeClient();

    await listLog(client, type, "some-slug", { page: 1, limit: 20 });

    expect(client.GET).toHaveBeenCalledWith(path, {
      params: { path: { slug: "some-slug" }, query: { page: 1, limit: 20 } },
    });
  });
});

describe("deleteLog", () => {
  it("DELETEs /v1/log/{log_id} with the log id and headers", async () => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    await deleteLog(client, headers, 42);

    expect(client.DELETE).toHaveBeenCalledWith("/v1/log/{log_id}", {
      params: { path: { log_id: 42 } },
      headers,
    });
  });
});

describe("getUserLog", () => {
  it("GETs /v1/users/{username}/log with the username and query", async () => {
    const client = fakeClient();

    await getUserLog(client, "alice", { limit: 100 });

    expect(client.GET).toHaveBeenCalledWith("/v1/users/{username}/log", {
      params: { path: { username: "alice" }, query: { limit: 100 } },
    });
  });
});
