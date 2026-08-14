// @vitest-environment node
//
// Same split as `library.test.ts`: `followUser`/`unfollowUser` only
// dispatch to a single templated operation, so a minimal fake `ApiClient`
// suffices. `getFollowers`/`getFollowing` are exercised end-to-end against
// the MSW mock server instead, since they own their own `getApiClient()`
// call and status interpretation.
import { createApiClient, type ApiClient } from "@backlogg/api-client";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { MOCK_API_BASE_URL } from "@/test/msw/handlers";
import { server } from "@/test/msw/server";

vi.mock("@/lib/auth/session", () => ({
  getApiClient: () => createApiClient(MOCK_API_BASE_URL),
}));

const { followUser, unfollowUser, getFollowers, getFollowing } = await import("./follows");

function fakeClient(): ApiClient {
  return {
    POST: vi.fn().mockResolvedValue({ response: new Response(null, { status: 204 }) }),
    DELETE: vi.fn().mockResolvedValue({ response: new Response(null, { status: 204 }) }),
  } as unknown as ApiClient;
}

describe("followUser", () => {
  it("POSTs to /v1/users/{username}/follow with the given headers", async () => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    await followUser(client, headers, "alice");

    expect(client.POST).toHaveBeenCalledWith("/v1/users/{username}/follow", {
      params: { path: { username: "alice" } },
      headers,
    });
  });
});

describe("unfollowUser", () => {
  it("DELETEs to /v1/users/{username}/follow with the given headers", async () => {
    const client = fakeClient();
    const headers = { Authorization: "Bearer t" };

    await unfollowUser(client, headers, "alice");

    expect(client.DELETE).toHaveBeenCalledWith("/v1/users/{username}/follow", {
      params: { path: { username: "alice" } },
      headers,
    });
  });
});

const followPage = {
  items: [{ username: "bob", display_name: "Bob", avatar_url: null }],
  total: 1,
  page: 1,
  limit: 20,
};

describe("getFollowers", () => {
  it("returns ok with the paginated items on a 200", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/followers`, () => HttpResponse.json(followPage)),
    );

    expect(await getFollowers("alice")).toEqual({ ok: true, ...followPage });
  });

  it("forwards page/limit as query params", async () => {
    let capturedUrl: URL | undefined;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/followers`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json(followPage);
      }),
    );

    await getFollowers("alice", { page: 2, limit: 20 });

    expect(capturedUrl?.searchParams.get("page")).toBe("2");
    expect(capturedUrl?.searchParams.get("limit")).toBe("20");
  });

  it("returns ok: false on a 404 (unknown username)", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/followers`, () =>
        HttpResponse.json({ detail: "Username not found" }, { status: 404 }),
      ),
    );

    expect(await getFollowers("ghost")).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/followers`, () => HttpResponse.error()),
    );

    expect(await getFollowers("alice")).toEqual({ ok: false });
  });
});

describe("getFollowing", () => {
  it("returns ok with the paginated items on a 200", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/following`, () => HttpResponse.json(followPage)),
    );

    expect(await getFollowing("alice")).toEqual({ ok: true, ...followPage });
  });

  it("returns ok: false on a 404 (unknown username)", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/following`, () =>
        HttpResponse.json({ detail: "Username not found" }, { status: 404 }),
      ),
    );

    expect(await getFollowing("ghost")).toEqual({ ok: false });
  });

  it("returns ok: false when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/users/:username/following`, () => HttpResponse.error()),
    );

    expect(await getFollowing("alice")).toEqual({ ok: false });
  });
});
