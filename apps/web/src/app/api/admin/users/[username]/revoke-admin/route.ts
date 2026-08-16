import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { env } from "@/lib/env";

type RoleGrantOut = components["schemas"]["RoleGrantOut"];
type RouteParams = { params: Promise<{ username: string }> };

/**
 * POST /api/admin/users/{username}/revoke-admin
 *
 * Proxies `POST /v1/admin/users/{username}/revoke-admin` (FE-30,
 * `docs/api.md`): revokes `is_admin` from the target user. Mirrors
 * `../grant-admin/route.ts` exactly (same `X-API-Key` + Bearer double gate,
 * same `apiFetch` auto-refresh, same status mapping) — see that file's doc
 * comment for the shared pattern/rationale. Self-revocation and revoking
 * another superadmin are both allowed by the backend on purpose (`docs/api.md`),
 * so this route does not special-case either.
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
      client.POST("/v1/admin/users/{username}/revoke-admin", {
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

    return NextResponse.json({ error: "revoke_admin_failed" }, { status: 502 });
  } catch (error) {
    console.error("POST /api/admin/users/[username]/revoke-admin: failed to reach the API", error);
    return NextResponse.json({ error: "revoke_admin_failed" }, { status: 502 });
  }
}
