/**
 * Route prefixes that require an authenticated session.
 *
 * These are matched against the pathname AFTER the locale segment has been
 * stripped (e.g. `/en/library` -> `/library`). Pages for some of these do not
 * exist yet (they arrive in later features); they are listed here so the
 * optimistic proxy check protects them as soon as they land.
 *
 * NOTE: this module is imported by `proxy.ts`, so it must stay free of
 * server-only / Node APIs (the proxy runtime is restricted).
 */
export const PROTECTED_PREFIXES = [
  "/settings",
  "/library",
  "/notifications",
  "/feed",
  "/recommendations",
  // Not admin-specific authorization (the backend has no admin/staff user
  // role, `docs/schema.md`) — just the same signed-in baseline every other
  // private route gets. The real protection for `/v1/admin/*` calls is the
  // server-only `X-API-Key` injected by the Route Handlers under
  // `src/app/api/admin/**` (FE-28, see that route's doc comment).
  "/admin",
] as const;

/**
 * Given a pathname WITHOUT the locale prefix, decide whether it is protected.
 * Matches the exact prefix or any nested path (`/library`, `/library/123`).
 */
export function isProtectedPath(pathnameWithoutLocale: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) =>
      pathnameWithoutLocale === prefix ||
      pathnameWithoutLocale.startsWith(`${prefix}/`),
  );
}
