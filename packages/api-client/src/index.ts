import createClient, { type ClientOptions, type Client } from "openapi-fetch";
import type { paths } from "./schema.js";

/**
 * A fully typed openapi-fetch client bound to the backlogg backend `paths`.
 * Every method (GET/POST/PUT/PATCH/DELETE) is typed against the OpenAPI schema.
 */
export type ApiClient = Client<paths>;

/**
 * Options accepted by {@link createApiClient}, minus `baseUrl` which is a
 * required positional argument (the base URL must never be hardcoded in the
 * client; callers pass it explicitly).
 */
export type CreateApiClientOptions = Omit<ClientOptions, "baseUrl">;

/**
 * Build a typed API client for the backlogg backend.
 *
 * @param baseUrl Origin (and optional prefix) the API is served from, e.g.
 *   `https://api.example.com`. Paths in the schema already include `/v1`.
 * @param options Extra openapi-fetch options (custom `fetch`, `headers`, etc.).
 */
export function createApiClient(
  baseUrl: string,
  options: CreateApiClientOptions = {},
): ApiClient {
  return createClient<paths>({ baseUrl, ...options });
}

export type { paths, components, operations, webhooks } from "./schema.js";
export type { ClientOptions, Client } from "openapi-fetch";
