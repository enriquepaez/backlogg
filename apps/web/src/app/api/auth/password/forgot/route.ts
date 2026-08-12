import { NextResponse } from "next/server";

import { getApiClient } from "@/lib/auth/session";

type ForgotPayload = {
  email?: unknown;
};

/**
 * POST /api/auth/password/forgot
 *
 * Proxies `POST /v1/auth/password/forgot` (`ForgotPasswordRequest` in,
 * `MessageOut` out — see `docs/api.md`). Public: no session/Authorization
 * involved, this is how a signed-out user starts the recovery flow.
 *
 * The backend answers `202` unconditionally, whether or not the email is
 * registered (no enumeration) — this proxy mirrors that: any well-formed
 * body reaching the backend collapses to the same `202`, and
 * `forgot-password-form.tsx` renders one static neutral message regardless.
 * Only a malformed request body (missing/non-string `email`) or a `422` from
 * the backend's own validation short-circuits before/after the call — both
 * still don't reveal whether the address exists, since neither depends on
 * the email being registered.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { email } = (payload as ForgotPayload) ?? {};
  if (typeof email !== "string" || email.length === 0) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { response } = await getApiClient().POST("/v1/auth/password/forgot", {
    body: { email },
  });

  if (response.status === 202) {
    return NextResponse.json({ ok: true }, { status: 202 });
  }

  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  return NextResponse.json(
    { error: "forgot_password_failed" },
    { status: response.status || 500 },
  );
}
