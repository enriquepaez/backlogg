import { NextResponse } from "next/server";

import { getUserProfile, type UserProfile } from "@/lib/library";

type RouteParams = { params: Promise<{ username: string }> };

/**
 * GET /api/users/{username}/library_counts
 *
 * FE-48: backs `library-status-counts.tsx`'s `useQuery` — the profile page's
 * public per-status library counts (`UserOut.library_counts`, `docs/api.md`),
 * split out from the full `GET /v1/users/{username}` response
 * `getUserProfile` (`@/lib/library`) already fetches so the widget's client
 * `useQuery` refetch (triggered by `viewer-status-slot.tsx`'s cross
 * invalidation of `queryKeys.library.counts.all`, `@/lib/queries/query-keys
 * .ts`) doesn't have to re-request the whole profile (bio, avatar,
 * follower/following counts, ...) just for four numbers.
 *
 * `getUserProfile` is public — no auth/token to forward — same "self-
 * contained, own `getApiClient()`" shape as the `/u/{username}` page's own
 * server-side call to it (`@/lib/library`'s doc comment). `library-status-
 * counts.tsx` can't call `getUserProfile` directly itself: it transitively
 * imports `server-only` (via `@/lib/auth/session`), so a Client Component
 * needs this BFF route the same way `ViewerStatusSlot`/`RatingWidget`/etc.
 * need theirs.
 */
export async function GET(_request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { username } = await params;

  const result = await getUserProfile(username);
  if (result.status === "ok") {
    return NextResponse.json(
      { counts: result.profile.library_counts satisfies UserProfile["library_counts"] },
      { status: 200 },
    );
  }
  if (result.status === "not-found") {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  return NextResponse.json({ error: "get_library_counts_failed" }, { status: 502 });
}
