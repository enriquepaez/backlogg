import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";

/**
 * POST /api/auth/verify/confirm
 *
 * Proxies `POST /v1/auth/verify/confirm` (`VerifyConfirmRequest` in,
 * `MessageOut` out — see `docs/api.md`). Public: unlike `verify/request`, this
 * does NOT need a session — the single-use token in the body (from the link
 * emailed to the user) is the credential, so `/verify-email?token=` can call
 * it even for a visitor with no cookies at all.
 *
 * Propagates 400 (token invalid, expired or already used) as-is; anything
 * else collapses to a generic failure the page treats as an unknown error.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { token } = (payload as { token?: unknown }) ?? {};
  if (typeof token !== "string" || token.length === 0) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { response } = await getApiClient().POST("/v1/auth/verify/confirm", {
    body: { token },
  });

  if (response.status === 200) {
    return NextResponse.json({ ok: true });
  }

  if (response.status === 400) {
    return NextResponse.json({ error: "invalid_token" }, { status: 400 });
  }

  return NextResponse.json(
    { error: "verify_confirm_failed" },
    { status: response.status || 500 },
  );
}
