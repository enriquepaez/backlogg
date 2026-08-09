/**
 * Auth cookie names, centralized and overridable via env.
 *
 * Kept in a dedicated module (free of `server-only` / Node APIs) so it can be
 * imported both by server-only helpers and by `proxy.ts`, whose runtime is
 * restricted. The browser never reads these values (they are httpOnly).
 */
export const ACCESS_COOKIE = process.env.AUTH_ACCESS_COOKIE ?? "bl_access";
export const REFRESH_COOKIE = process.env.AUTH_REFRESH_COOKIE ?? "bl_refresh";
