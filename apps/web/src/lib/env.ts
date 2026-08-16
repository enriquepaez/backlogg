import "server-only";

/**
 * Server-only environment access.
 *
 * All values here are read lazily (via getters) so that importing this module
 * during `next build` never throws when an optional runtime variable is unset.
 * They are resolved the first time they are actually used at request time.
 */
function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export const env = {
  /**
   * Origin of the backlogg backend, WITHOUT the `/v1` prefix
   * (the OpenAPI paths already include it). Example: `http://localhost:8000`.
   */
  get API_INTERNAL_URL(): string {
    return required("API_INTERNAL_URL");
  },

  /**
   * Shared secret sent as the `X-API-Key` header to `/v1/admin/*` (FE-28,
   * `docs/api.md`). Must match the backend's own `ADMIN_API_KEY`
   * (`backlogg/admin/auth.py`) — this is the BFF's copy of the same value,
   * read server-side ONLY (never imported from a Client Component) and
   * injected into admin proxy calls under `src/app/api/admin/**`. Left unset
   * on purpose in most environments; callers must treat a missing value the
   * same as the backend's own 503 rather than let this throw uncaught.
   */
  get ADMIN_API_KEY(): string {
    return required("ADMIN_API_KEY");
  },
} as const;
