import "server-only";

import { cache } from "react";
import { cookies } from "next/headers";

import type { ApiClient, components } from "@backlogg/api-client";

import { readAccessToken } from "./auth/cookies";
import { authHeader, getApiClient, refreshSession } from "./auth/session";

export type UserMe = components["schemas"]["UserMeOut"];

/**
 * A single typed call against the `/v1` API. Receives the typed client and the
 * access token to attach (via {@link authHeader}). The shape mirrors what
 * openapi-fetch returns so callers can hand back the raw call directly.
 */
type ApiCall<T> = (
  client: ApiClient,
  accessToken: string | undefined,
) => Promise<{ data?: T; error?: unknown; response: Response }>;

export type ApiFetchResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

/**
 * Server-side authenticated fetch helper for `/v1/*`.
 *
 * Reads the access token from the httpOnly cookie, runs `call`, and — if the
 * backend answers 401 — rotates the refresh token ONCE, rewrites the cookies,
 * and retries the call with the new access token. If the refresh itself fails,
 * cookies are cleared and the original 401 is propagated.
 *
 * `401` and `429` are not part of the typed OpenAPI responses, so callers must
 * branch on `response.status`.
 */
export async function apiFetch<T>(call: ApiCall<T>): Promise<ApiFetchResult<T>> {
  const store = await cookies();
  const accessToken = readAccessToken(store);

  const first = await call(getApiClient(), accessToken);
  if (first.response.status !== 401) {
    return first;
  }

  const refreshedToken = await refreshSession(store);
  if (!refreshedToken) {
    // Refresh failed: cookies already cleared, propagate the original 401.
    return first;
  }

  return call(getApiClient(), refreshedToken);
}

/**
 * Current authenticated user, or `null` if there is no valid session.
 *
 * Memoized per-request with React `cache()` so multiple Server Components can
 * call it without duplicate `/v1/users/me` requests. Doubles as a session
 * verifier (a non-null result means the session is valid / was refreshed).
 */
export const getCurrentUser = cache(async (): Promise<UserMe | null> => {
  const { data, response } = await apiFetch<UserMe>((client, token) =>
    client.GET("/v1/users/me", { headers: authHeader(token) }),
  );
  return response.status === 200 && data ? data : null;
});
