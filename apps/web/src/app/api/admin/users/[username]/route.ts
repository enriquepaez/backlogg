import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

type RouteParams = { params: Promise<{ username: string }> };

/**
 * GET /api/admin/users/{username}
 *
 * Proxies `GET /v1/admin/users/{username}` (FE-33, `docs/api.md`): admin
 * detail for a single user. Same base pattern as `../route.ts` (the list) and
 * `../../reports/route.ts` — this app's own `ADMIN_API_KEY` (`@/lib/env`,
 * `server-only`) is read here, server-side ONLY, and injected as
 * `X-API-Key` on the call to the backend.
 *
 * Lives at the same `[username]/` level as the `ban`/`unban`/`grant-admin`/
 * `revoke-admin` subroutes — those are unaffected, this is a sibling
 * `route.ts` handling `GET` for the folder itself.
 *
 * `/admin/users/{username}` itself (`@/app/[locale]/admin/users/[username]/page.tsx`)
 * does NOT call this route — as a Server Component it calls
 * `getAdminUserDetail` (`@/lib/admin-users.ts`) directly, skipping the extra
 * HTTP hop (see that module's own doc comment). This route exists for
 * parity with the rest of `/api/admin/**` and any future Client Component
 * caller that would need the same data from the browser.
 *
 * Status mapping mirrors `../route.ts`: this app's own `ADMIN_API_KEY`
 * unset -> 503; backend 401 -> 401; backend 404 -> 404; backend 503 -> 503;
 * anything else -> 502.
 */
export async function GET(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { username } = await params;

  let apiKey: string;
  try {
    apiKey = env.ADMIN_API_KEY;
  } catch {
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  try {
    const { data, response } = await getApiClient().GET("/v1/admin/users/{username}", {
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

    return NextResponse.json({ error: "admin_user_detail_failed" }, { status: 502 });
  } catch (error) {
    console.error("GET /api/admin/users/[username]: failed to reach the API", error);
    return NextResponse.json({ error: "admin_user_detail_failed" }, { status: 502 });
  }
}
