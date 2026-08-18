import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { LIBRARY_STATUSES, STATUS_COLOR_CLASSES } from "@/lib/library-types";
import type { UserProfile } from "@/lib/library";
import { cn } from "@/lib/utils";

export type LibraryStatusCountsProps = {
  username: string;
  counts: UserProfile["library_counts"];
};

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
 * Self-contained (fetches its own translations), same house style as
 * `LibraryPagination`, rather than threading translators down from the page
 * — the status labels reuse `Library.statusTabs.*`, already the canonical
 * copy for these four values (`/u/[username]/library/page.tsx`'s
 * `StatusTabs`).
 */
export async function LibraryStatusCounts({ username, counts }: LibraryStatusCountsProps) {
  const [t, tStatus] = await Promise.all([
    getTranslations("Profile.library"),
    getTranslations("Library.statusTabs"),
  ]);

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
