import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { createList } from "@/lib/lists";

type ListCreate = components["schemas"]["ListCreate"];
type UserListOut = components["schemas"]["UserListOut"];

type CreatePayload = {
  title?: unknown;
  description?: unknown;
  is_public?: unknown;
};

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

/**
 * POST /api/lists
 *
 * Proxies `POST /v1/lists` (`ListCreate` in, `UserListOut` out, 201 — the
 * slug is derived server-side from `title`, `docs/api.md`). Uses `apiFetch`
 * (the FE-4 helper) so an expired access token is transparently refreshed
 * once before falling back to 401, same as every other authenticated BFF
 * route (`app/api/users/me/route.ts`, `app/api/users/[username]/follow/route.ts`).
 *
 * `create-list-dialog.tsx` already validates with `listSchema` client-side;
 * this only re-checks the wire shape defensively (same spirit as
 * `PATCH /api/users/me`'s `isNullableString` guards) before forwarding.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { title, description, is_public: isPublic } = (payload as CreatePayload) ?? {};

  if (typeof title !== "string" || title.trim().length === 0) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  if (!isNullableString(description ?? null)) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  if (isPublic !== undefined && typeof isPublic !== "boolean") {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const body: ListCreate = {
    title,
    description: (description as string | null | undefined) ?? null,
    is_public: (isPublic as boolean | undefined) ?? true,
  };

  const { data, response } = await apiFetch<UserListOut>((client, token) =>
    createList(client, authHeader(token), body),
  );

  if (response.status === 201 && data) {
    return NextResponse.json(data, { status: 201 });
  }

  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  return NextResponse.json({ error: "create_list_failed" }, { status: response.status || 500 });
}
