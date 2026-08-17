import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { apiFetch } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";

type UserMeOut = components["schemas"]["UserMeOut"];
type UploadAvatarBody = components["schemas"]["Body_upload_avatar_v1_users_me_avatar_post"];

/**
 * POST /api/users/me/avatar
 *
 * Proxies `POST /v1/users/me/avatar` (feature 51 — multipart, field `file`,
 * `UserMeOut` out on success). `avatar-upload-field.tsx` posts here directly
 * via `XMLHttpRequest` (for upload progress, `fetch` can't report it), so
 * this route re-reads the incoming multipart body with `request.formData()`
 * and forwards the same `File` through untouched — never buffered into
 * memory as anything else, streamed as far as the platform allows.
 *
 * The generated `Body_upload_avatar_v1_users_me_avatar_post` type models
 * `file` as `string` (OpenAPI has no first-class binary/File type — FastAPI
 * only declares `contentMediaType`), so the real `FormData` we hand to the
 * typed client needs a cast: `openapi-fetch`'s `defaultBodySerializer`
 * passes a `FormData` instance through unchanged (see its source), it's
 * only the static type that doesn't have a better shape to offer here.
 *
 * 401/413/422/503 aren't part of the typed OpenAPI responses (only 200/422
 * are — same caveat `api-fetch.ts` documents for 401/429 elsewhere), so this
 * branches on `response.status` like every other proxy route.
 */
export async function POST(request: Request): Promise<NextResponse> {
  let incoming: FormData;
  try {
    incoming = await request.formData();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const file = incoming.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const outgoing = new FormData();
  outgoing.append("file", file);

  const { data, response } = await apiFetch<UserMeOut>((client, token) =>
    client.POST("/v1/users/me/avatar", {
      body: outgoing as unknown as UploadAvatarBody,
      headers: authHeader(token),
    }),
  );

  if (response.status === 200 && data) {
    return NextResponse.json(data, { status: 200 });
  }

  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  if (response.status === 413) {
    return NextResponse.json({ error: "too_large" }, { status: 413 });
  }

  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  if (response.status === 503) {
    return NextResponse.json({ error: "storage_unavailable" }, { status: 503 });
  }

  return NextResponse.json({ error: "upload_avatar_failed" }, { status: response.status || 500 });
}

/**
 * DELETE /api/users/me/avatar
 *
 * Proxies `DELETE /v1/users/me/avatar` (204, no body, idempotent —
 * `docs/api.md`).
 */
export async function DELETE(): Promise<NextResponse> {
  const { response } = await apiFetch<unknown>((client, token) =>
    client.DELETE("/v1/users/me/avatar", { headers: authHeader(token) }),
  );

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  return NextResponse.json({ error: "delete_avatar_failed" }, { status: response.status || 500 });
}
