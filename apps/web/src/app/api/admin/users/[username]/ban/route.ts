import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

type RouteParams = { params: Promise<{ username: string }> };

/**
 * POST /api/admin/users/{username}/ban
 *
 * Proxies `POST /v1/admin/users/{username}/ban` (FE-30, `docs/api.md`): bans
 * a user (blocks login/refresh, hides all of their reviews). Same base
 * pattern as `../../../reviews/[id]/hide/route.ts` — only the shared
 * `X-API-Key` is required (no caller session), read server-side ONLY from
 * `@/lib/env` and injected here. `username` is forwarded as-is, same as
 * `../../../../users/[username]/follow/route.ts` — the backend itself
 * validates existence (404) rather than this route pre-checking it.
 *
 * Idempotent on the backend, so no special-casing for a repeat call. Status
 * mapping mirrors `../../../reviews/[id]/hide/route.ts`: this app's own
 * `ADMIN_API_KEY` unset -> 503; backend 401 -> 401; backend 404 -> 404;
 * anything else -> 502.
 */
export async function POST(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { username } = await params;

  let apiKey: string;
  try {
    apiKey = env.ADMIN_API_KEY;
  } catch {
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  try {
    const { data, response } = await getApiClient().POST("/v1/admin/users/{username}/ban", {
      params: {
        header: { "x-api-key": apiKey },
        path: { username },
      },
    });

    if (response.status === 200 && data) {
      return NextResponse.json(data, { status: 200 });
    }
    if (response.status === 401) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    if (response.status === 404) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }
    if (response.status === 503) {
      return NextResponse.json({ error: "not_configured" }, { status: 503 });
    }

    return NextResponse.json({ error: "ban_user_failed" }, { status: 502 });
  } catch (error) {
    console.error("POST /api/admin/users/[username]/ban: failed to reach the API", error);
    return NextResponse.json({ error: "ban_user_failed" }, { status: 502 });
  }
}
