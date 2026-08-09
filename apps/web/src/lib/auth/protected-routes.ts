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
  "/lists",
  "/feed",
  "/recommendations",
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
