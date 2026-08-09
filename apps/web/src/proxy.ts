import createMiddleware from "next-intl/middleware";
import { NextResponse, type NextRequest } from "next/server";

import { routing } from "./i18n/routing";
import { REFRESH_COOKIE } from "./lib/auth/cookie-names";
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
 * Proxy (Next 16 middleware). Wraps the next-intl routing middleware and adds
 * an OPTIMISTIC auth check: for protected routes, if there is no refresh cookie
 * present, redirect to the locale login page. This only reads the cookie — the
 * real session validation happens server-side in the Data Access Layer.
 */
export default function proxy(request: NextRequest): ReturnType<typeof intlMiddleware> {
  const { pathname } = request.nextUrl;
  const { locale, rest } = splitLocale(pathname);

  if (isProtectedPath(rest)) {
    const hasSession = Boolean(request.cookies.get(REFRESH_COOKIE)?.value);
    if (!hasSession) {
      const loginUrl = new URL(`/${locale}/login`, request.nextUrl);
      return NextResponse.redirect(loginUrl);
    }
  }

  return intlMiddleware(request);
}

export const config = {
  // Match all pathnames except for API routes, Next internals and static
  // assets (anything with a dot). This is what runs the locale negotiation.
  matcher: "/((?!api|trpc|_next|_vercel|.*\\..*).*)",
};
