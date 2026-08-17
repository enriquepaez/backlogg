import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

import { adminUserActionReasonFromStatus, callAdminUserAction } from "./admin-user-actions";

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("adminUserActionReasonFromStatus", () => {
  it.each([
    [403, "forbidden"],
    [401, "unauthorized"],
    [404, "not_found"],
    [503, "not_configured"],
    [500, "unknown"],
    [418, "unknown"],
  ] as const)("maps status %i to %s", (status, reason) => {
    expect(adminUserActionReasonFromStatus(status)).toBe(reason);
  });
});

describe("callAdminUserAction", () => {
  it("posts to /api/admin/users/{username}/{action} and returns the parsed body on 200", async () => {
    let calledUrl: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/ban", ({ request, params }) => {
        calledUrl = request.url;
        expect(params.username).toBe("troll");
        return HttpResponse.json({ username: "troll", is_banned: true });
      }),
    );

    const result = await callAdminUserAction("ban", "troll");

    expect(result).toEqual({ ok: true, data: { username: "troll", is_banned: true } });
    expect(calledUrl).toContain("/api/admin/users/troll/ban");
  });

  it("URL-encodes the username", async () => {
    let calledUrl: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/unban", ({ request }) => {
        calledUrl = request.url;
        return HttpResponse.json({ username: "a b", is_banned: false });
      }),
    );

    await callAdminUserAction("unban", "a b");

    expect(calledUrl).toContain("/api/admin/users/a%20b/unban");
  });

  it("returns a mapped error reason on a non-200 response", async () => {
    server.use(
      http.post("/api/admin/users/:username/grant-admin", () =>
        HttpResponse.json({ error: "forbidden" }, { status: 403 }),
      ),
    );

    const result = await callAdminUserAction("grant-admin", "alice");

    expect(result).toEqual({ ok: false, reason: "forbidden" });
  });

  it("returns reason 'unknown' when the request throws", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("network down"));

    const result = await callAdminUserAction("revoke-admin", "alice");

    expect(result).toEqual({ ok: false, reason: "unknown" });
  });
});
