import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { env } from "@/lib/env";

type RoleGrantOut = components["schemas"]["RoleGrantOut"];
type RouteParams = { params: Promise<{ username: string }> };

/**
 * POST /api/admin/users/{username}/grant-admin
 *
 * Proxies `POST /v1/admin/users/{username}/grant-admin` (FE-30,
 * `docs/api.md`): grants `is_admin` to the target user.
 *
 * Deliberate deviation from every other `/v1/admin/*` route under
 * `src/app/api/admin/**` (`../../../reviews/[id]/hide/route.ts`, `../ban/route.ts`,
 * etc.): the backend requires BOTH the shared `X-API-Key` (read server-side
 * ONLY from `@/lib/env`, same as those) AND the signed-in caller's own Bearer
 * access token, and checks server-side that the caller is `is_superadmin` —
 * so this route uses `apiFetch` (the FE-4 helper) for transparent
 * access-token refresh, same as every other authenticated BFF route
 * (`@/app/api/users/[username]/follow/route.ts`), on top of injecting the
 * `X-API-Key`. `AdminModerationPanel`'s own visibility check (only rendering
 * this action for a caller whose own `/v1/users/me` says
 * `is_superadmin === true`) is UI-only, never trusted as the real gate — the
 * 403 handled below is the actual authorization, enforced server-side by the
 * backend regardless of what the client sends.
 *
 * `username` is forwarded as-is (backend validates existence, 404 if
 * unknown). Idempotent on the backend, so no special-casing for a repeat
 * call. Status mapping: this app's own `ADMIN_API_KEY` unset -> 503; backend
 * 401 (missing/incorrect `X-API-Key`, or missing/invalid/expired Bearer even
 * after `apiFetch`'s one refresh attempt) -> 401; backend 403 (authenticated
 * but not `is_superadmin`) -> 403; backend 404 -> 404; anything else -> 502.
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
    const { data, response } = await apiFetch<RoleGrantOut>((client, token) =>
      client.POST("/v1/admin/users/{username}/grant-admin", {
        params: {
          header: { "x-api-key": apiKey },
          path: { username },
        },
        headers: authHeader(token),
      }),
    );

    if (response.status === 200 && data) {
      return NextResponse.json(data, { status: 200 });
    }
    if (response.status === 401) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    if (response.status === 403) {
      return NextResponse.json({ error: "forbidden" }, { status: 403 });
    }
    if (response.status === 404) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }
    if (response.status === 503) {
      return NextResponse.json({ error: "not_configured" }, { status: 503 });
    }

    return NextResponse.json({ error: "grant_admin_failed" }, { status: 502 });
  } catch (error) {
    console.error("POST /api/admin/users/[username]/grant-admin: failed to reach the API", error);
    return NextResponse.json({ error: "grant_admin_failed" }, { status: 502 });
  }
}
