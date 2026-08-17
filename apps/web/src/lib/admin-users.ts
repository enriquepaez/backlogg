import type { components } from "@backlogg/api-client";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

export type AdminUserOut = components["schemas"]["AdminUserOut"];

export type AdminUserDetailResult =
  | { status: "ok"; user: AdminUserOut }
  | { status: "not-found" }
  | { status: "error"; reason: "unauthorized" | "not_configured" | "unknown" };

/**
 * `GET /v1/admin/users/{username}` (FE-33, `docs/api.md`): admin-only detail
 * for a single user (role/ban flags, `created_at`), gated by the shared
 * `X-API-Key` secret (`env.ADMIN_API_KEY`, `server-only`) instead of a caller
 * session — same auth as every other read under `/v1/admin/*`. Unlike
 * `getUserProfile`/`getUserReviews` (`./library.ts`/`./user-content.ts`),
 * this can't be a plain unauthenticated call, hence its own module here
 * rather than alongside those.
 *
 * Used directly by `/admin/users/{username}` itself
 * (`@/app/[locale]/admin/users/[username]/page.tsx`), a Server Component
 * that can safely import `env` (`server-only`) and skip an extra HTTP hop
 * through this app's own `/api/admin/users/{username}` BFF route — same
 * reasoning `getUserProfile`/`getUserReviews` already apply to public reads,
 * just with the admin key attached here. That BFF route
 * (`@/app/api/admin/users/[username]/route.ts`) exists independently, for
 * any future Client Component caller (mirroring every other `/api/admin/**`
 * route) and is NOT implemented on top of this helper — every other BFF
 * route under `src/app/api/admin/**` is a small, self-contained proxy with
 * its own inline `env.ADMIN_API_KEY`/`getApiClient()` call, and this one
 * follows that same house style rather than introducing a shared-helper
 * exception for just this one route.
 */
export async function getAdminUserDetail(username: string): Promise<AdminUserDetailResult> {
  let apiKey: string;
  try {
    apiKey = env.ADMIN_API_KEY;
  } catch {
    return { status: "error", reason: "not_configured" };
  }

  try {
    const { data, response } = await getApiClient().GET("/v1/admin/users/{username}", {
      params: { header: { "x-api-key": apiKey }, path: { username } },
    });
    if (response.status === 200 && data) return { status: "ok", user: data };
    if (response.status === 404) return { status: "not-found" };
    if (response.status === 401) return { status: "error", reason: "unauthorized" };
    if (response.status === 503) return { status: "error", reason: "not_configured" };
    return { status: "error", reason: "unknown" };
  } catch (error) {
    console.error(`getAdminUserDetail(${username}): failed to reach the API`, error);
    return { status: "error", reason: "unknown" };
  }
}
