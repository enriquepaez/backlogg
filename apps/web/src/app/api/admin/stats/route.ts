import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

/**
 * GET /api/admin/stats
 *
 * Proxies `GET /v1/admin/stats` (FE-28, `docs/api.md`): per-type catalog
 * counts + last sync timestamp. Establishes the base pattern for every other
 * `/v1/admin/*` Route Handler that will land under `src/app/api/admin/**`
 * (FE-29 report queue, FE-30 moderation) — this app's own `ADMIN_API_KEY`
 * (`@/lib/env`, `server-only`) is read here, server-side ONLY, and injected
 * as `X-API-Key` on the call to the backend. It is never included in this
 * response's body, so it never reaches the browser or the rendered HTML —
 * `AdminStatsPanel` (`@/components/admin-stats-panel.tsx`), the only caller,
 * is a Client Component that talks to this route, never to the backend
 * directly.
 *
 * No user-session check here on purpose: `/v1/admin/*` auth is entirely the
 * shared `X-API-Key` secret, not tied to any account — this Route Handler
 * doesn't read cookies at all. The page that renders this panel (`/admin`,
 * `@/app/[locale]/admin/page.tsx`) is what performs the real authorization:
 * it requires both a signed-in session (same baseline gate as `/settings`,
 * `/recommendations`) AND `user.is_admin === true` (`admin_role_gate` fix,
 * `users.is_admin` — `docs/schema.md`), redirecting a signed-in-but-not-admin
 * user to `/` before this route is ever reached from that page. This route
 * itself has no independent notion of "who is calling" beyond the API key,
 * so it must never be exposed to a Client Component that isn't gated the
 * same way `AdminStatsPanel`'s parent page is.
 *
 * Status mapping mirrors the backend's own `verify_api_key` dependency
 * (`backlogg/admin/auth.py`):
 * - This app's own `ADMIN_API_KEY` unset -> 503, same status the backend
 *   itself would answer with for the equivalent condition on its side —
 *   without it there is no key to send at all, so the request is never made.
 * - Backend 401 (missing/incorrect key) -> 401, passed through unchanged.
 * - Backend 503 (`ADMIN_API_KEY` unset on the backend) -> 503, passed
 *   through unchanged.
 * - Anything else (network failure, unexpected status) -> 502.
 */
export async function GET(): Promise<NextResponse> {
  let apiKey: string;
  try {
    apiKey = env.ADMIN_API_KEY;
  } catch {
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  try {
    const { data, response } = await getApiClient().GET("/v1/admin/stats", {
      params: { header: { "x-api-key": apiKey } },
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

    return NextResponse.json({ error: "admin_stats_failed" }, { status: 502 });
  } catch (error) {
    console.error("GET /api/admin/stats: failed to reach the API", error);
    return NextResponse.json({ error: "admin_stats_failed" }, { status: 502 });
  }
}
