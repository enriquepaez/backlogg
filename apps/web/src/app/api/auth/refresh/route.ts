import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { refreshSession } from "@/lib/auth/session";

/**
 * POST /api/auth/refresh
 *
 * Reads the refresh cookie and rotates the token pair against
 * `POST /v1/auth/refresh`. On success, BOTH cookies are rewritten with the new
 * pair. On failure (missing / expired / reused refresh) both cookies are
 * cleared and 401 is returned.
 */
export async function POST(): Promise<NextResponse> {
  const store = await cookies();
  const newAccessToken = await refreshSession(store);

  if (!newAccessToken) {
    return NextResponse.json({ error: "session_expired" }, { status: 401 });
  }

  return NextResponse.json({ ok: true });
}
