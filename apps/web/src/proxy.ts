import createMiddleware from "next-intl/middleware";
import { NextResponse, type NextRequest } from "next/server";

import { routing } from "./i18n/routing";
import { REFRESH_COOKIE } from "./lib/auth/cookie-names";
import { applyRefreshOutcome, refreshBeforeRender } from "./lib/auth/proxy-refresh";
import { isProtectedPath } from "./lib/auth/protected-routes";

const intlMiddleware = createMiddleware(routing);

/**
 * Split a locale-prefixed pathname into its locale segment and the remainder.
 * `localePrefix` is "always", so every matched path starts with `/en` or `/es`.
 */
function splitLocale(pathname: string): {
  locale: string;
  rest: string;
} {
  const segments = pathname.split("/"); // ["", "en", "library", ...]
  const maybeLocale = segments[1];
  const locale = routing.locales.includes(
    maybeLocale as (typeof routing.locales)[number],
  )
    ? maybeLocale
    : routing.defaultLocale;
  const rest = "/" + segments.slice(2).join("/");
  return { locale, rest: rest === "/" ? "/" : rest.replace(/\/$/, "") };
}

/**
 * Proxy (Next 16 middleware). Wraps the next-intl routing middleware and adds:
 *
 * 1. A proactive access-token refresh (see `lib/auth/proxy-refresh.ts` for the
 *    full rationale) so that by the time the route renders — and any Server
 *    Component calls `getCurrentUser()` — the access cookie is already fresh.
 *    This is what makes it safe for `getCurrentUser()` to run during render
 *    (the app shell's nav does, on every page).
 * 2. An auth check for protected routes: if there is no valid session after
 *    the refresh attempt above, redirect to the locale login page. This only
 *    reads cookies — the real session validation happens server-side in the
 *    Data Access Layer (`getCurrentUser()`).
 */
export default async function proxy(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;
  const { locale, rest } = splitLocale(pathname);

  const refreshOutcome = await refreshBeforeRender(request);

  if (isProtectedPath(rest)) {
    const hasSession = request.cookies.has(REFRESH_COOKIE);
    if (!hasSession) {
      const loginUrl = new URL(`/${locale}/login`, request.nextUrl);
      return applyRefreshOutcome(
        NextResponse.redirect(loginUrl),
        request,
        refreshOutcome,
      );
    }
  }

  const response = intlMiddleware(request);
  return applyRefreshOutcome(response, request, refreshOutcome);
}

export const config = {
  matcher: [
    {
      // Match all pathnames except for API routes, Next internals and
      // static assets (anything with a dot). This is what runs the locale
      // negotiation and the token-refresh check above.
      source: "/((?!api|trpc|_next|_vercel|.*\\..*).*)",
      // Skip prefetch requests (Link hover/viewport prefetching, which the
      // app shell's `getCurrentUser()` usage makes frequent since every
      // route becomes dynamic once a layout reads cookies). Two concurrent
      // requests racing to rotate the SAME refresh token would make the
      // second one look like reuse to the backend and revoke the session —
      // excluding prefetches removes the dominant source of that race.
      // Real (non-prefetch) navigations are unaffected and still refresh.
      // See `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md`,
      // "Negative matching" and "RSC requests and rewrites" (the
      // `next-router-prefetch` header is stripped from `request.headers`
      // INSIDE the proxy function body, so this can only be checked here,
      // at the matcher level, against the raw incoming request).
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
