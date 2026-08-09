import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { setAuthCookies } from "@/lib/auth/cookies";
import { getApiClient } from "@/lib/auth/session";

/**
 * POST /api/auth/login
 *
 * Proxies credentials to `POST /v1/auth/login`. On success, stores the rotated
 * token pair as httpOnly cookies and returns a minimal body — tokens are NEVER
 * exposed to the client. Propagates 401 (bad credentials / banned) and 429
 * (rate limit) including the `Retry-After` header.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { username, password } =
    (payload as { username?: unknown; password?: unknown }) ?? {};
  if (typeof username !== "string" || typeof password !== "string") {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { data, response } = await getApiClient().POST("/v1/auth/login", {
    body: { username, password },
  });

  if (response.status === 200 && data) {
    const store = await cookies();
    setAuthCookies(store, data);
    return NextResponse.json({ ok: true });
  }

  if (response.status === 429) {
    const res = NextResponse.json({ error: "rate_limited" }, { status: 429 });
    const retryAfter = response.headers.get("Retry-After");
    if (retryAfter) {
      res.headers.set("Retry-After", retryAfter);
    }
    return res;
  }

  const status = response.status === 401 ? 401 : response.status;
  return NextResponse.json(
    { error: status === 401 ? "invalid_credentials" : "login_failed" },
    { status },
  );
}
