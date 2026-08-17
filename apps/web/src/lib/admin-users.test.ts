// @vitest-environment node
//
// Same MSW-backed pattern as `library.test.ts`/`user-content.test.ts`, plus
// the `@/lib/env` mock from `../app/api/admin/reports/route.test.ts` (this
// helper reads `env.ADMIN_API_KEY`, which the other two public lib modules
// never need to).
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

const { getAdminUserDetail } = await import("./admin-users");

const aliceFixture = {
  username: "alice",
  display_name: "Alice A.",
  avatar_url: null,
  is_admin: false,
  is_superadmin: false,
  is_banned: false,
  created_at: "2026-05-25T02:03:12Z",
};

afterEach(() => {
  envMock.ADMIN_API_KEY = "s3cr3t";
});

describe("getAdminUserDetail", () => {
  it("injects X-API-Key and returns ok with the user on a 200", async () => {
    let forwardedKey: string | null = null;
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/:username`, ({ request }) => {
        forwardedKey = request.headers.get("x-api-key");
        return HttpResponse.json(aliceFixture);
      }),
    );

    expect(await getAdminUserDetail("alice")).toEqual({ status: "ok", user: aliceFixture });
    expect(forwardedKey).toBe("s3cr3t");
  });

  it("returns not-found on a 404", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/:username`, () =>
        HttpResponse.json({ detail: "User not found" }, { status: 404 }),
      ),
    );

    expect(await getAdminUserDetail("ghost")).toEqual({ status: "not-found" });
  });

  it("returns error: unauthorized on a 401", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/:username`, () =>
        HttpResponse.json({ detail: "Invalid or missing X-API-Key header." }, { status: 401 }),
      ),
    );

    expect(await getAdminUserDetail("alice")).toEqual({
      status: "error",
      reason: "unauthorized",
    });
  });

  it("returns error: not_configured on a 503 from the backend", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/:username`, () =>
        HttpResponse.json({ detail: "Admin API key is not configured." }, { status: 503 }),
      ),
    );

    expect(await getAdminUserDetail("alice")).toEqual({
      status: "error",
      reason: "not_configured",
    });
  });

  it("returns error: not_configured without calling the backend when this app's own ADMIN_API_KEY is unset", async () => {
    envMock.ADMIN_API_KEY = undefined;
    const backendCall = vi.fn();
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/:username`, () => {
        backendCall();
        return HttpResponse.json(aliceFixture);
      }),
    );

    expect(await getAdminUserDetail("alice")).toEqual({
      status: "error",
      reason: "not_configured",
    });
    expect(backendCall).not.toHaveBeenCalled();
  });

  it("returns error: unknown on an unexpected backend status", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/:username`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    expect(await getAdminUserDetail("alice")).toEqual({ status: "error", reason: "unknown" });
  });

  it("returns error: unknown when the network fails", async () => {
    server.use(
      http.get(`${MOCK_API_BASE_URL}/v1/admin/users/:username`, () => HttpResponse.error()),
    );

    expect(await getAdminUserDetail("alice")).toEqual({ status: "error", reason: "unknown" });
  });
});
