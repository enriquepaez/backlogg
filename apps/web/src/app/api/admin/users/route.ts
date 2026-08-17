import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

/** Same default/max as `../reports/route.ts` (`docs/api.md`'s `GET /v1/admin/users` default/max `limit`). */
const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

function parsePositiveInt(raw: string | null, fallback: number, max?: number): number {
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return fallback;
  }
  return max ? Math.min(parsed, max) : parsed;
}

/**
 * `is_banned`/`is_admin` are optional booleans on the backend (`docs/api.md`):
 * only the literal strings `"true"`/`"false"` are recognized, anything else
 * (missing, typo'd, `"1"`, ...) is treated as "no filter" and omitted from
 * the backend call — same defensive spirit as `parseStatus` in
 * `../reports/route.ts` for its own `status` query param.
 */
function parseBoolean(raw: string | null): boolean | undefined {
  if (raw === "true") return true;
  if (raw === "false") return false;
  return undefined;
}

/**
 * GET /api/admin/users?is_banned=&is_admin=&search=&page=&limit=
 *
 * Proxies `GET /v1/admin/users` (FE-33, `docs/api.md`): the paginated user
 * directory for the admin backoffice, ordered by `username` asc, with
 * optional `is_banned`/`is_admin` filters (combinable and independent) and an
 * optional `search` free-text filter (case-insensitive substring match
 * against username/display name/email on the backend — `email` is never
 * returned in the response, only used to match). `search` is trimmed here;
 * an empty string after trimming is omitted from the backend call entirely,
 * same defensive spirit as the boolean filters below. Same base pattern as
 * `../reports/route.ts` and `../stats/route.ts` — this app's own
 * `ADMIN_API_KEY` (`@/lib/env`, `server-only`) is read here, server-side
 * ONLY, and injected as `X-API-Key` on the call to the backend.
 * `AdminUsersDirectoryPanel` (`@/components/admin-users-directory-panel.tsx`),
 * the only caller, is a Client Component that talks to this route, never to
 * the backend directly, so the key never reaches the browser.
 *
 * No user-session check here on purpose — see `../stats/route.ts`'s doc
 * comment: `/v1/admin/*` auth is entirely the shared `X-API-Key` secret, and
 * the real authorization (signed-in AND `user.is_admin`) already happened in
 * the page that renders `AdminUsersDirectoryPanel` (`/admin`,
 * `@/app/[locale]/admin/page.tsx`).
 *
 * Status mapping mirrors `../reports/route.ts`: this app's own
 * `ADMIN_API_KEY` unset -> 503; backend 401 -> 401; backend 503 -> 503;
 * anything else -> 502.
 */
export async function GET(request: Request): Promise<NextResponse> {
  let apiKey: string;
  try {
    apiKey = env.ADMIN_API_KEY;
  } catch {
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  const url = new URL(request.url);
  const isBanned = parseBoolean(url.searchParams.get("is_banned"));
  const isAdmin = parseBoolean(url.searchParams.get("is_admin"));
  const search = url.searchParams.get("search")?.trim() || undefined;
  const page = parsePositiveInt(url.searchParams.get("page"), 1);
  const limit = parsePositiveInt(url.searchParams.get("limit"), DEFAULT_LIMIT, MAX_LIMIT);

  try {
    const { data, response } = await getApiClient().GET("/v1/admin/users", {
      params: {
        header: { "x-api-key": apiKey },
        query: { is_banned: isBanned, is_admin: isAdmin, search, page, limit },
      },
    });

    if (response.status === 200 && data) {
      return NextResponse.json(data, { status: 200 });
    }
    if (response.status === 401) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    if (response.status === 503) {
      return NextResponse.json({ error: "not_configured" }, { status: 503 });
    }

    return NextResponse.json({ error: "admin_users_failed" }, { status: 502 });
  } catch (error) {
    console.error("GET /api/admin/users: failed to reach the API", error);
    return NextResponse.json({ error: "admin_users_failed" }, { status: 502 });
  }
}
