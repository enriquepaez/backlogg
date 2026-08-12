import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";

type MessageOut = components["schemas"]["MessageOut"];

/**
 * POST /api/auth/verify/request
 *
 * Proxies `POST /v1/auth/verify/request` (no body, `MessageOut` out — see
 * `docs/api.md`). Unlike `verify/confirm`, this REQUIRES a session: it is
 * how an already-authenticated user asks for a fresh verification link
 * (surfaced from the account menu, `user-nav.tsx`). Uses `apiFetch` (the
 * FE-4 helper, see `src/lib/api-fetch.ts`) so an expired access token is
 * transparently refreshed once before falling back to 401 — the same
 * resilience `getCurrentUser` gets, now exercised by a mutating call instead
 * of a plain `GET`.
 */
export async function POST(): Promise<NextResponse> {
  const { response } = await apiFetch<MessageOut>((client, token) =>
    client.POST("/v1/auth/verify/request", { headers: authHeader(token) }),
  );

  if (response.status === 202) {
    return NextResponse.json({ ok: true }, { status: 202 });
  }

  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  return NextResponse.json(
    { error: "verify_request_failed" },
    { status: response.status || 500 },
  );
}
