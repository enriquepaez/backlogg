import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";

type ResetPayload = {
  token?: unknown;
  new_password?: unknown;
};

/**
 * POST /api/auth/password/reset
 *
 * Proxies `POST /v1/auth/password/reset` (`ResetPasswordRequest` in,
 * `MessageOut` out — see `docs/api.md`). Public: like `verify/confirm`, the
 * single-use token in the body (from the link emailed to the user) is the
 * credential, so `/reset-password?token=` can call it for a visitor with no
 * cookies at all.
 *
 * On `200` the backend has already revoked every active refresh token for
 * the account (forces re-login everywhere) — this route does not touch any
 * local session cookies, since a signed-out visitor following a recovery
 * link has none to clear, and a signed-in one resetting their own password
 * from another tab still needs their local cookies invalidated the normal
 * way (next authenticated call simply fails with 401, same as any other
 * revoked/expired session).
 *
 * Propagates `400` (token invalid, expired or already used) and `422`
 * (validation, e.g. `new_password` too short) with their original status
 * codes; anything else collapses to a generic failure.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { token, new_password: newPassword } = (payload as ResetPayload) ?? {};
  if (
    typeof token !== "string" ||
    token.length === 0 ||
    typeof newPassword !== "string" ||
    newPassword.length === 0
  ) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { response } = await getApiClient().POST("/v1/auth/password/reset", {
    body: { token, new_password: newPassword },
  });

  if (response.status === 200) {
    return NextResponse.json({ ok: true });
  }

  if (response.status === 400) {
    return NextResponse.json({ error: "invalid_token" }, { status: 400 });
  }

  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  return NextResponse.json(
    { error: "reset_password_failed" },
    { status: response.status || 500 },
  );
}
