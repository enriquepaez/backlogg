import { NextResponse } from "next/server";

import { apiFetch, getCurrentUser } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { isCatalogType } from "@/lib/catalog-types";
import {
  deleteLibraryStatus,
  getViewerLibraryStatus,
  isLibraryStatus,
  putLibraryStatus,
  type LibraryStatusOut,
} from "@/lib/library";

type RouteParams = { params: Promise<{ type: string; slug: string }> };

type PutPayload = { status?: unknown };

/**
 * GET /api/{type}/{slug}/library
 *
 * Backs `ViewerStatusSlot`'s initial load, same shape/rationale as
 * `GET /api/{type}/{slug}/rating`: always 200 (never 401) so the widget can
 * render its own anonymous prompt, distinguished via `authenticated`. Reads
 * the caller's status via `getViewerLibraryStatus` (`@/lib/library`) — see
 * that module's doc comment for why this proxies the item detail endpoint
 * instead of a dedicated "my status" one.
 *
 * Deliberately does NOT `revalidateTag` the item detail cache (see the
 * `PUT`/`DELETE` handlers below) — this is a read.
 */
export async function GET(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.json({ authenticated: false, status: null }, { status: 200 });
  }

  const { data, response } = await apiFetch<{ viewer_status?: string | null }>((client, token) =>
    getViewerLibraryStatus(client, authHeader(token), type, slug),
  );

  if (response.status === 200 && data) {
    return NextResponse.json({ authenticated: true, status: data.viewer_status ?? null }, { status: 200 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json(
    { error: "get_library_status_failed" },
    { status: response.status || 500 },
  );
}

/**
 * PUT /api/{type}/{slug}/library
 *
 * Proxies `PUT /v1/{type}/{slug}/library` (`LibraryEntryIn` in,
 * `LibraryStatusOut` out — `docs/api.md`): full upsert of the caller's
 * backlog status. Uses `apiFetch` (FE-4) for transparent access-token
 * refresh, same pattern as `PUT /api/{type}/{slug}/rating`.
 *
 * Unlike that rating route, this does NOT call `revalidateTag` on the item
 * detail cache: `viewer_status` is per-viewer and the item detail page's
 * public/ISR-cached fetch (`getItemDetail`, `src/lib/catalog.ts`) never sends
 * auth headers, so `viewer_status` is always `null` in that cached response
 * regardless of any caller's actual status — there is nothing stale to
 * invalidate (see `progress/current.md`, FE-20 plan).
 */
export async function PUT(request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { status } = (payload as PutPayload) ?? {};
  if (typeof status !== "string" || !isLibraryStatus(status)) {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const { data, response } = await apiFetch<LibraryStatusOut>((client, token) =>
    putLibraryStatus(client, authHeader(token), type, slug, status),
  );

  if (response.status === 200 && data) {
    return NextResponse.json(data, { status: 200 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  return NextResponse.json({ error: "set_library_failed" }, { status: response.status || 500 });
}

/**
 * DELETE /api/{type}/{slug}/library
 *
 * Proxies `DELETE /v1/{type}/{slug}/library` (204, no body — `docs/api.md`).
 * Same `apiFetch` auto-refresh as `PUT` above, and the same "no
 * `revalidateTag`" reasoning (see that handler's doc comment).
 */
export async function DELETE(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  const { response } = await apiFetch<undefined>((client, token) =>
    deleteLibraryStatus(client, authHeader(token), type, slug),
  );

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  if (response.status === 401) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (response.status === 404) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json({ error: "delete_library_failed" }, { status: response.status || 500 });
}
