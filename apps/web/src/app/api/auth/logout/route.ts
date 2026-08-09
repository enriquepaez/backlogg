import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import {
  clearAuthCookies,
  readAccessToken,
  readRefreshToken,
} from "@/lib/auth/cookies";
import { authHeader, getApiClient } from "@/lib/auth/session";

/**
 * POST /api/auth/logout
 *
 * Revokes the refresh token against `POST /v1/auth/logout` (Bearer access +
 * `{ refresh_token }`) and ALWAYS clears both cookies, returning 204. Fully
 * idempotent: if there is no session, or the backend rejects the call, the
 * client still ends up logged out locally.
 */
export async function POST(): Promise<NextResponse> {
  const store = await cookies();
  const accessToken = readAccessToken(store);
  const refreshToken = readRefreshToken(store);

  if (refreshToken) {
    try {
      await getApiClient().POST("/v1/auth/logout", {
        body: { refresh_token: refreshToken },
        headers: authHeader(accessToken),
      });
    } catch {
      // Best-effort revocation: network / backend errors must not block logout.
    }
  }

  clearAuthCookies(store);
  return new NextResponse(null, { status: 204 });
}
