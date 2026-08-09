import "server-only";

import type { cookies } from "next/headers";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "./cookie-names";

export { ACCESS_COOKIE, REFRESH_COOKIE } from "./cookie-names";

/**
 * Mutable cookie store type as returned (awaited) inside Route Handlers and
 * Server Actions, where `.set` / `.delete` are allowed.
 */
export type CookieStore = Awaited<ReturnType<typeof cookies>>;

/**
 * Lifetimes mirror the backend token settings:
 *   JWT_EXPIRE_MINUTES = 15   (access)
 *   REFRESH_EXPIRE_DAYS = 30  (refresh)
 */
const ACCESS_MAX_AGE = 15 * 60; // 15 minutes, in seconds
const REFRESH_MAX_AGE = 30 * 24 * 60 * 60; // 30 days, in seconds

type CookieOptions = Parameters<CookieStore["set"]>[2];

function baseCookieOptions(): CookieOptions {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
  };
}

export function accessCookieOptions(): CookieOptions {
  return { ...baseCookieOptions(), maxAge: ACCESS_MAX_AGE };
}

export function refreshCookieOptions(): CookieOptions {
  return { ...baseCookieOptions(), maxAge: REFRESH_MAX_AGE };
}

/** Read the current access token from the cookie store, if any. */
export function readAccessToken(store: CookieStore): string | undefined {
  return store.get(ACCESS_COOKIE)?.value;
}

/** Read the current refresh token from the cookie store, if any. */
export function readRefreshToken(store: CookieStore): string | undefined {
  return store.get(REFRESH_COOKIE)?.value;
}

/** Persist a freshly issued token pair as httpOnly cookies. */
export function setAuthCookies(
  store: CookieStore,
  tokens: { access_token: string; refresh_token: string },
): void {
  store.set(ACCESS_COOKIE, tokens.access_token, accessCookieOptions());
  store.set(REFRESH_COOKIE, tokens.refresh_token, refreshCookieOptions());
}

/** Remove both auth cookies. Safe to call when they are absent (idempotent). */
export function clearAuthCookies(store: CookieStore): void {
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
}
