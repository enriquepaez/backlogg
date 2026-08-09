import "server-only";

import type { NextRequest, NextResponse } from "next/server";

import { ACCESS_COOKIE, accessCookieOptions, REFRESH_COOKIE, refreshCookieOptions } from "./cookies";
import { getApiClient } from "./session";

/**
 * Proactively rotate the access token INSIDE `proxy.ts`, before the route
 * renders — this is the fix for the cookie-write-swallowed-in-RSC-render bug
 * flagged in the FE-4 review (see `progress/history.md`, FE-4 entry).
 *
 * The problem: Next.js forbids `cookies().set()` during Server Component
 * rendering (`node_modules/next/dist/docs/01-app/03-api-reference/04-functions/cookies.md`,
 * "Setting cookies is not supported during Server Component rendering. To
 * modify cookies, invoke a Server Function from the client or use a Route
 * Handler."). `getCurrentUser()` (api-fetch.ts) is now called from a Server
 * Component (the nav, in render) on every page. If the access cookie were
 * missing there, `apiFetch`'s in-render fallback would rotate the refresh
 * token against the backend (which revokes the OLD refresh token as part of
 * rotation) but `session.ts`'s `safeSet` would silently swallow the cookie
 * write (read-only context) — the browser never receives the new pair. The
 * NEXT request then replays the now-revoked refresh token, the backend
 * detects reuse, and revokes every session for that user.
 *
 * The fix: do the rotation in `proxy.ts` instead. Proxy runs BEFORE
 * rendering and is one of the few places (with Server Actions / Route
 * Handlers) allowed to emit `Set-Cookie`
 * (`.../03-file-conventions/route.md`; `02-guides/backend-for-frontend.md`,
 * "Manipulating data" / "Callback URLs" examples write cookies via
 * `NextResponse`). By the time the Server Component renders, the access
 * cookie is already fresh, so `apiFetch`'s in-render fallback is never
 * exercised on the happy path.
 *
 * This mutates `request.cookies` (not just the outgoing response) so the
 * NEW token is visible to `cookies()` reads inside the SAME request's
 * render — Next.js propagates request cookie mutations downstream via
 * `NextResponse.next({ request })` / `.rewrite({ request })`, which
 * `next-intl`'s middleware already does internally when it re-emits the
 * request (`node_modules/next-intl/dist/esm/development/middleware/middleware.js`,
 * function `next()`: `new Headers(request.headers)` is built from the
 * request AFTER our mutation, then handed to `NextResponse.next`/`.rewrite`
 * via `{ request: { headers } }`). This is the same pattern used by
 * Supabase's/Auth.js's Next.js middleware auth-refresh helpers.
 */
export type RefreshOutcome = "refreshed" | "cleared" | "skipped";

export async function refreshBeforeRender(
  request: NextRequest,
): Promise<RefreshOutcome> {
  const hasAccessToken = request.cookies.has(ACCESS_COOKIE);
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;

  // Already have a (presumably valid) access token, or no session at all:
  // nothing to do. The access cookie's `maxAge` mirrors the backend's JWT
  // lifetime, so its absence is the signal that a refresh is due.
  if (hasAccessToken || !refreshToken) {
    return "skipped";
  }

  try {
    const { data, response } = await getApiClient().POST("/v1/auth/refresh", {
      body: { refresh_token: refreshToken },
    });

    if (response.status === 200 && data) {
      request.cookies.set(ACCESS_COOKIE, data.access_token);
      request.cookies.set(REFRESH_COOKIE, data.refresh_token);
      return "refreshed";
    }

    // Expired / reused / revoked refresh token: the session is dead. Clear
    // it so the (possibly-protected) route sees an unauthenticated request
    // rather than replaying a token the backend already rejected.
    request.cookies.delete(ACCESS_COOKIE);
    request.cookies.delete(REFRESH_COOKIE);
    return "cleared";
  } catch {
    // Backend unreachable: fail open. The render's own DAL call will get a
    // fresh chance (and, worst case, hits the rare in-render fallback path
    // this function exists to avoid) rather than us clearing a session that
    // might still be perfectly valid.
    return "skipped";
  }
}

/**
 * Mirror the outcome of {@link refreshBeforeRender} onto the outgoing
 * response so the browser actually persists (or drops) the cookies. Reads
 * the rotated values back from `request.cookies`, which `refreshBeforeRender`
 * already updated.
 */
export function applyRefreshOutcome(
  response: NextResponse,
  request: NextRequest,
  outcome: RefreshOutcome,
): NextResponse {
  if (outcome === "refreshed") {
    response.cookies.set(
      ACCESS_COOKIE,
      request.cookies.get(ACCESS_COOKIE)!.value,
      accessCookieOptions(),
    );
    response.cookies.set(
      REFRESH_COOKIE,
      request.cookies.get(REFRESH_COOKIE)!.value,
      refreshCookieOptions(),
    );
  } else if (outcome === "cleared") {
    response.cookies.delete(ACCESS_COOKIE);
    response.cookies.delete(REFRESH_COOKIE);
  }
  return response;
}
