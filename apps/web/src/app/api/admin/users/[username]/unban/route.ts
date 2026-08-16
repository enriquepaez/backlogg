import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

type RouteParams = { params: Promise<{ username: string }> };

/**
 * POST /api/admin/users/{username}/unban
 *
 * Proxies `POST /v1/admin/users/{username}/unban` (FE-30, `docs/api.md`):
 * lifts a ban. Mirrors `../ban/route.ts` exactly — see that file's doc
 * comment for the shared pattern/rationale.
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
    const { data, response } = await getApiClient().POST("/v1/admin/users/{username}/unban", {
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

    return NextResponse.json({ error: "unban_user_failed" }, { status: 502 });
  } catch (error) {
    console.error("POST /api/admin/users/[username]/unban: failed to reach the API", error);
    return NextResponse.json({ error: "unban_user_failed" }, { status: 502 });
  }
}
