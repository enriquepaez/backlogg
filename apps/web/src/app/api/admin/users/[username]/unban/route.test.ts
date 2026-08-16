// @vitest-environment node
//
// Mirrors `../ban/route.test.ts`.
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

const unbannedFixture = { username: "troll", is_banned: false };

function makeParams(username: string) {
  return { params: Promise.resolve({ username }) };
}

afterEach(() => {
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("POST /api/admin/users/[username]/unban", () => {
  it("injects X-API-Key and returns the moderation result on 200", async () => {
    let forwardedKey: string | null = null;
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/users/troll/unban`, ({ request }) => {
        forwardedKey = request.headers.get("x-api-key");
        return HttpResponse.json(unbannedFixture, { status: 200 });
      }),
    );

    const response = await POST(new Request("http://localhost"), makeParams("troll"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(unbannedFixture);
    expect(forwardedKey).toBe("s3cr3t");
  });

  it("returns 404 when the user doesn't exist", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/users/ghost/unban`, () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    const response = await POST(new Request("http://localhost"), makeParams("ghost"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 503 without calling the backend when this app's own ADMIN_API_KEY is unset", async () => {
    envMock.ADMIN_API_KEY = undefined;
    const backendCall = vi.fn();
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/users/troll/unban`, () => {
        backendCall();
        return HttpResponse.json(unbannedFixture, { status: 200 });
      }),
    );

    const response = await POST(new Request("http://localhost"), makeParams("troll"));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "not_configured" });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns 502 on an unexpected backend status", async () => {
    server.use(
      http.post(`${MOCK_API_BASE_URL}/v1/admin/users/troll/unban`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const response = await POST(new Request("http://localhost"), makeParams("troll"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "unban_user_failed" });
  });
});
