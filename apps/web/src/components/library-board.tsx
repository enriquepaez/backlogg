import { getTranslations } from "next-intl/server";

import { LibraryBoardCard } from "@/components/library-board-card";
import { isCatalogType } from "@/lib/catalog-types";
import {
  LIBRARY_STATUSES,
  STATUS_COLOR_CLASSES,
  type LibraryEntry,
  type LibraryStatusValue,
} from "@/lib/library-types";
import { cn } from "@/lib/utils";

/**
 * Same lowercase-and-validate mapping as `toCatalogType` (`@/lib/search`) —
 * reimplemented here instead of importing it so this file stays free of
 * `@/lib/search`'s transitive `server-only` import (via `@/lib/auth/session`,
 * see that file's doc comment). Not a problem for `page.tsx` itself, which
 * is only ever rendered inside the real Next.js server runtime, but this
 * component's own test (`library-board.test.tsx`) renders it directly under
 * plain Vitest/jsdom, which has no build-time alias for `server-only` and
 * fails to resolve the import outright.
 */
function toCatalogType(itemType: string) {
  const lower = itemType.toLowerCase();
  return isCatalogType(lower) ? lower : undefined;
}

export type LibraryBoardProps = {
  /** Sorted (`sortLibraryEntries`, same `?sort=` as the grid) entries per status, capped at `LIBRARY_BOARD_SCAN_LIMIT` — see `page.tsx`'s doc comment. */
  entriesByStatus: Record<LibraryStatusValue, LibraryEntry[]>;
  /**
   * Count shown in each column's header — `page.tsx` passes the backend's
   * exact `UserOut.library_counts[status]` when no type filter is active
   * (unaffected by the fetch cap below), or the length of the fetched
   * (possibly capped) `entriesByStatus[status]` when a type filter narrows
   * the board, since `library_counts` isn't broken down per type. See
   * `page.tsx`'s doc comment for the full rationale.
   */
  countsByStatus: Record<LibraryStatusValue, number>;
};

/**
 * Four-column board view for `/u/{username}/library` (FE-43), an
 * alternative to the flat poster grid — one column per
 * {@link LibraryStatusValue}, each headed by its FE-37 status color and
 * item count, holding compact `LibraryBoardCard`s. Self-contained (fetches
 * its own `Library` translations), same house style as
 * `LibraryStatusCounts`/`LibraryPagination`.
 *
 * No drag-and-drop in this iteration (explicit scope cut, FE-43's
 * description) — changing status still only happens from the item detail
 * page's `ViewerStatusSlot`.
 *
 * Responsive: a plain responsive grid (`grid-cols-1` -> `sm:grid-cols-2` ->
 * `lg:grid-cols-4`) rather than a horizontal-scroll strip, so columns stack
 * on mobile — consistent with every other grid in this app (the poster grid
 * this replaces, `LibraryStatusCounts`, `browse`/`search`), none of which
 * use horizontal scroll for their own responsive breakpoints.
 */
export async function LibraryBoard({ entriesByStatus, countsByStatus }: LibraryBoardProps) {
  const t = await getTranslations("Library");

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {LIBRARY_STATUSES.map((status) => {
        const entries = entriesByStatus[status];
        const count = countsByStatus[status];
        return (
          <div key={status} className="flex flex-col overflow-hidden rounded-lg border border-border">
            <div
              className={cn(
                "flex items-center justify-between gap-2 px-3 py-2 text-sm font-semibold",
                STATUS_COLOR_CLASSES[status],
              )}
            >
              <span>{t(`statusTabs.${status}`)}</span>
              <span>{count}</span>
            </div>
            <div className="flex flex-1 flex-col gap-2 bg-muted/30 p-2">
              {entries.length === 0 ? (
                <p className="px-1 py-2 text-xs text-muted-foreground">{t("board.columnEmpty")}</p>
              ) : (
                entries.map((entry) => {
                  const itemType = toCatalogType(entry.item.item_type);
                  return (
                    <LibraryBoardCard
                      key={`${entry.item.item_type}-${entry.item.slug}`}
                      title={entry.item.title}
                      posterUrl={entry.item.poster_url}
                      href={itemType ? `/${itemType}/${entry.item.slug}` : undefined}
                    />
                  );
                })
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
