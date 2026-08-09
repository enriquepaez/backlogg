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
} as const;
