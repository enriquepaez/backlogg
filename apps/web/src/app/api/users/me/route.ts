import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { apiFetch } from "@/lib/api-fetch";
import { clearAuthCookies } from "@/lib/auth/cookies";
import { authHeader } from "@/lib/auth/session";

type UserMeOut = components["schemas"]["UserMeOut"];
type UserUpdate = components["schemas"]["UserUpdate"];

type PatchPayload = {
  display_name?: unknown;
  bio?: unknown;
  avatar_url?: unknown;
};

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

/**
 * PATCH /api/users/me
 *
 * Proxies `PATCH /v1/users/me` (`UserUpdate` in, `UserMeOut` out —
 * `docs/api.md`). Uses `apiFetch` (the FE-4 helper) so an expired access
 * token is transparently refreshed once before falling back to 401, same as
 * `verify/request/route.ts`. All three fields are optional/nullable on the
 * backend; `account-profile-form.tsx` always sends all three (a full-form
 * submit, not a per-field diff), translating a blanked-out input to `null`
 * so clearing a field round-trips correctly.
 */
export async function PATCH(request: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const {
    display_name: displayName,
    bio,
    avatar_url: avatarUrl,
  } = (payload as PatchPayload) ?? {};

  if (
    !isNullableString(displayName) ||
    !isNullableString(bio) ||
    !isNullableString(avatarUrl)
  ) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const body: UserUpdate = {
    display_name: displayName,
    bio,
    avatar_url: avatarUrl,
  };

  const { data, response } = await apiFetch<UserMeOut>((client, token) =>
    client.PATCH("/v1/users/me", { body, headers: authHeader(token) }),
  );

  if (response.status === 200 && data) {
    return NextResponse.json(data, { status: 200 });
  }

  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  return NextResponse.json(
    { error: "update_profile_failed" },
    { status: response.status || 500 },
  );
}

/**
 * DELETE /api/users/me
 *
 * Proxies `DELETE /v1/users/me` (204, no body — `docs/api.md`). The backend
 * already invalidates every refresh token for the account as part of the
 * delete (GDPR cascade), so — unlike `logout/route.ts`, which separately
 * calls `POST /v1/auth/logout` to revoke the refresh token — there is
 * nothing left server-side to revoke here. Only the local httpOnly cookies
 * need clearing, and only on a confirmed 204: a 401 means there was no
 * session to end in the first place, so cookies are left as-is (nothing to
 * clean up, and clearing them would mask the real error from the caller).
 */
export async function DELETE(): Promise<NextResponse> {
  const { response } = await apiFetch<unknown>((client, token) =>
    client.DELETE("/v1/users/me", { headers: authHeader(token) }),
  );

  if (response.status === 204) {
    const store = await cookies();
    clearAuthCookies(store);
    return new NextResponse(null, { status: 204 });
  }

  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  return NextResponse.json(
    { error: "delete_account_failed" },
    { status: response.status || 500 },
  );
}
