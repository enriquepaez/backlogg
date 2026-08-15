import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { deleteList, updateList } from "@/lib/lists";

type ListUpdate = components["schemas"]["ListUpdate"];
type UserListOut = components["schemas"]["UserListOut"];

type RouteParams = { params: Promise<{ slug: string }> };

type UpdatePayload = {
  title?: unknown;
  description?: unknown;
  is_public?: unknown;
};

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

/**
 * PATCH /api/lists/{slug}
 *
 * Proxies `PATCH /v1/lists/{slug}` (`ListUpdate` in, `UserListOut` out, 200 —
 * owner only, `docs/api.md`). `edit-list-dialog.tsx` always sends all three
 * fields together (a full-form submit, not a per-field diff), same pattern
 * as `account-profile-form.tsx`/`PATCH /api/users/me` — so this route
 * requires all three present rather than treating a missing field as
 * "leave untouched", even though the backend's `ListUpdate` itself allows a
 * genuine partial update.
 */
export async function PATCH(request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { slug } = await params;

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { title, description, is_public: isPublic } = (payload as UpdatePayload) ?? {};

  if (typeof title !== "string" || title.trim().length === 0) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  if (!isNullableString(description ?? null)) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  if (typeof isPublic !== "boolean") {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const body: ListUpdate = {
    title,
    description: (description as string | null | undefined) ?? null,
    is_public: isPublic,
  };

  const { data, response } = await apiFetch<UserListOut>((client, token) =>
    updateList(client, authHeader(token), slug, body),
  );

  if (response.status === 200 && data) {
    return NextResponse.json(data, { status: 200 });
  }

  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 403) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  return NextResponse.json({ error: "update_list_failed" }, { status: response.status || 500 });
}

/**
 * DELETE /api/lists/{slug}
 *
 * Proxies `DELETE /v1/lists/{slug}` (204, no body, cascades the list's items
 * — owner only, `docs/api.md`). Same `apiFetch` auto-refresh as `PATCH` above.
 */
export async function DELETE(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { slug } = await params;

  const { response } = await apiFetch<undefined>((client, token) =>
    deleteList(client, authHeader(token), slug),
  );

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 403) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json({ error: "delete_list_failed" }, { status: response.status || 500 });
}
