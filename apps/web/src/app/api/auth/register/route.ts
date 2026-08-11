import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";

type RegisterPayload = {
  username?: unknown;
  email?: unknown;
  password?: unknown;
  display_name?: unknown;
};

/**
 * POST /api/auth/register
 *
 * Proxies `POST /v1/auth/register` (`UserCreate` in, `UserMeOut` out — see
 * `docs/api.md`). Unlike `/api/auth/login`, a successful registration does
 * NOT create a session: the backend returns the created profile, not a token
 * pair, so there is nothing to store as cookies here. `register-form.tsx`
 * is responsible for chaining a second call to `/api/auth/login` with the
 * same credentials once this answers 201, so the user ends up signed in
 * without re-typing anything (see that file's doc comment for the full
 * rationale). This route only ever creates the account.
 *
 * Propagates 409 (username/email already in use), 422 (validation) and 429
 * (rate limit, with `Retry-After`) with their original status codes.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { username, email, password, display_name: displayName } =
    (payload as RegisterPayload) ?? {};

  if (
    typeof username !== "string" ||
    typeof email !== "string" ||
    typeof password !== "string" ||
    (displayName !== undefined && displayName !== null && typeof displayName !== "string")
  ) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { response } = await getApiClient().POST("/v1/auth/register", {
    body: {
      username,
      email,
      password,
      display_name: displayName ?? null,
    },
  });

  if (response.status === 201) {
    return NextResponse.json({ ok: true }, { status: 201 });
  }

  if (response.status === 409) {
    return NextResponse.json({ error: "conflict" }, { status: 409 });
  }

  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  if (response.status === 429) {
    const res = NextResponse.json({ error: "rate_limited" }, { status: 429 });
    const retryAfter = response.headers.get("Retry-After");
    if (retryAfter) {
      res.headers.set("Retry-After", retryAfter);
    }
    return res;
  }

  return NextResponse.json({ error: "register_failed" }, { status: response.status || 500 });
}
