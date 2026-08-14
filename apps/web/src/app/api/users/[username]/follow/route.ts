import { NextResponse } from "next/server";

import { apiFetch, getCurrentUser } from "@/lib/api-fetch";
import { authHeader } from "@/lib/auth/session";
import { followUser, getFollowing, unfollowUser } from "@/lib/follows";

type RouteParams = { params: Promise<{ username: string }> };

/**
 * Widest page the backend allows for `GET /v1/users/{username}/following`
 * (`le=100`, `backlogg/follows/routes.py`) — see `@/lib/follows`'s doc
 * comment for why the GET handler below scans this single page instead of
 * calling a dedicated "am I following" endpoint that doesn't exist.
 */
const FOLLOWING_SCAN_LIMIT = 100;

/**
 * GET /api/users/{username}/follow
 *
 * Backs `FollowWidget`'s initial load, same shape/rationale as
 * `GET /api/{type}/{slug}/library`: always 200 (never 401) so the widget can
 * render its own anonymous prompt, distinguished via `authenticated`.
 *
 * Known limitation: only the viewer's first `FOLLOWING_SCAN_LIMIT` follows
 * (newest first, `docs/api.md`) are scanned — a viewer following more than
 * that who followed `{username}` long ago would see `following: false`
 * here even though the backend relationship exists. The toggle itself stays
 * correct either way (idempotent on both ends), so this only affects the
 * widget's initial visual state. Same trade-off already accepted by
 * `listRatings`'s "my rating" scan (`@/lib/ratings`'s doc comment).
 */
export async function GET(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { username } = await params;

  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.json({ authenticated: false, following: false }, { status: 200 });
  }

  const result = await getFollowing(user.username, { limit: FOLLOWING_SCAN_LIMIT });
  const following = result.ok && result.items.some((item) => item.username === username);
  return NextResponse.json({ authenticated: true, following }, { status: 200 });
}

/**
 * POST /api/users/{username}/follow
 *
 * Proxies `POST /v1/users/{username}/follow` (204, no body, idempotent —
 * `docs/api.md`). Uses `apiFetch` (FE-4) for transparent access-token
 * refresh, same pattern as every other authenticated BFF route.
 */
export async function POST(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { username } = await params;

  const { response } = await apiFetch<undefined>((client, token) =>
    followUser(client, authHeader(token), username),
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
  if (response.status === 422) {
    return NextResponse.json({ error: "validation_error" }, { status: 422 });
  }

  return NextResponse.json({ error: "follow_failed" }, { status: response.status || 500 });
}

/**
 * DELETE /api/users/{username}/follow
 *
 * Proxies `DELETE /v1/users/{username}/follow` (204, no body, idempotent —
 * `docs/api.md`). Same `apiFetch` auto-refresh as `POST` above.
 */
export async function DELETE(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { username } = await params;

  const { response } = await apiFetch<undefined>((client, token) =>
    unfollowUser(client, authHeader(token), username),
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

  return NextResponse.json({ error: "unfollow_failed" }, { status: response.status || 500 });
}
