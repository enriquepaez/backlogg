"use client";

import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { Link } from "@/i18n/navigation";
import { LIBRARY_STATUSES, STATUS_COLOR_CLASSES } from "@/lib/library-types";
import type { UserProfile } from "@/lib/library";
import { queryKeys } from "@/lib/queries/query-keys";
import { cn } from "@/lib/utils";

export type LibraryStatusCountsProps = {
  username: string;
  counts: UserProfile["library_counts"];
};

type LibraryCountsResponse = { counts: UserProfile["library_counts"] };

async function fetchLibraryCounts(username: string): Promise<LibraryCountsResponse> {
  const response = await fetch(`/api/users/${username}/library_counts`);
  if (!response.ok) {
    throw new Error(`unexpected status ${response.status}`);
  }
  return (await response.json()) as LibraryCountsResponse;
}

/**
 * Prominent per-status library count summary for the profile page (FE-39,
 * `/u/{username}`) — a colored link per status (FE-37's
 * `STATUS_COLOR_CLASSES`, the same design tokens `StatusTabs`'s active tab
 * and `CatalogCard`'s library badge already use), each pointing at the
 * matching filtered view of `/u/{username}/library`. Distinct from
 * `StatusTabs` (`/u/[username]/library/page.tsx`), which toggles the
 * *current* filter in place — the counts here always link out, since the
 * profile page itself has no status filter of its own. `counts` is public
 * (`GET /v1/users/{username}`, FE-31), so this renders identically on the
 * viewer's own profile and anyone else's.
 *
 * A Client Component as of FE-48 (previously an `async` Server Component
 * reading `getTranslations` directly) so it can subscribe to TanStack
 * Query's cache via `useQuery`: `viewer-status-slot.tsx` invalidates
 * `queryKeys.library.counts.all` whenever the viewer changes their own
 * backlog status on an item detail page — an entirely separate route/
 * component tree with no shared props — so this is the half of that
 * cross-widget invalidation (FE-48 acceptance) that actually re-fetches and
 * re-renders. `counts` (the page's own server-side `getUserProfile` call,
 * `src/app/[locale]/u/[username]/page.tsx`) is passed through as `useQuery`'s
 * `initialData`: the very first paint (including SSR/pre-hydration HTML)
 * renders the already-known-correct counts with no loading flash and no
 * redundant fetch — only a *later* invalidation triggers a real network
 * call, silently replacing `data` once it resolves (stale-while-revalidate)
 * without ever needing a distinct loading state of its own.
 */
export function LibraryStatusCounts({ username, counts: initialCounts }: LibraryStatusCountsProps) {
  const t = useTranslations("Profile.library");
  const tStatus = useTranslations("Library.statusTabs");

  const countsQuery = useQuery({
    queryKey: queryKeys.library.counts.byUsername(username),
    queryFn: () => fetchLibraryCounts(username),
    initialData: { counts: initialCounts },
  });
  const counts = countsQuery.data.counts;

  return (
    <div role="group" aria-label={t("countsLabel")} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {LIBRARY_STATUSES.map((status) => (
        <Link
          key={status}
          href={{ pathname: `/u/${username}/library`, query: { status } }}
          className={cn(
            "flex flex-col items-center gap-1 rounded-lg px-4 py-3 text-center shadow-sm transition-opacity hover:opacity-90",
            STATUS_COLOR_CLASSES[status],
          )}
        >
          <span className="text-2xl font-semibold tabular-nums">{counts[status]}</span>
          <span className="text-xs font-medium uppercase tracking-wide">{tStatus(status)}</span>
        </Link>
      ))}
    </div>
  );
}
