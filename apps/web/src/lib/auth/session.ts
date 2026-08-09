import "server-only";

import { createApiClient, type ApiClient } from "@backlogg/api-client";

import { env } from "../env";
import {
  clearAuthCookies,
  readRefreshToken,
  setAuthCookies,
  type CookieStore,
} from "./cookies";

/**
 * Lazily-constructed typed client for the internal `/v1` API. Built on first
 * use (never at import time) so `next build` does not require `API_INTERNAL_URL`.
 */
let cachedClient: ApiClient | null = null;

export function getApiClient(): ApiClient {
  if (!cachedClient) {
    cachedClient = createApiClient(env.API_INTERNAL_URL);
  }
  return cachedClient;
}

/** Build the Authorization header for a given (optional) access token. */
export function authHeader(
  accessToken: string | undefined,
): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

/**
 * Rotate the refresh token against `/v1/auth/refresh`.
 *
 * On success: rewrites BOTH cookies with the rotated pair and returns the new
 * access token. On failure (missing/expired/reused refresh): clears both
 * cookies and returns `null`.
 *
 * Cookie writes are best-effort: if invoked from a context where cookies cannot
 * be mutated (e.g. during a Server Component render), the write is swallowed and
 * the new access token is still returned so the caller can retry in-memory.
 */
export async function refreshSession(
  store: CookieStore,
): Promise<string | null> {
  const refreshToken = readRefreshToken(store);
  if (!refreshToken) {
    safeClear(store);
    return null;
  }

  const { data, response } = await getApiClient().POST("/v1/auth/refresh", {
    body: { refresh_token: refreshToken },
  });

  if (response.status === 200 && data) {
    safeSet(store, data);
    return data.access_token;
  }

  safeClear(store);
  return null;
}

function safeSet(
  store: CookieStore,
  tokens: { access_token: string; refresh_token: string },
): void {
  try {
    setAuthCookies(store, tokens);
  } catch {
    // Read-only cookie context (e.g. Server Component render); ignore.
  }
}

function safeClear(store: CookieStore): void {
  try {
    clearAuthCookies(store);
  } catch {
    // Read-only cookie context; ignore.
  }
}
