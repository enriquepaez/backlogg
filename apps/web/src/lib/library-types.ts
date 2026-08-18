import type { components } from "@backlogg/api-client";

/**
 * Framework-agnostic library/backlog vocabulary (FE-20): the `LibraryStatus`
 * value union plus a runtime mirror and type guard for it. No `server-only`
 * import (directly or transitively) — safe to import from Client Components
 * (`src/components/viewer-status-slot.tsx`, a "use client" component that
 * needs `LIBRARY_STATUSES` at runtime to render the four status buttons) as
 * well as Server Components.
 *
 * `./library.ts` holds the actual data-fetching functions (`putLibraryStatus`,
 * `getUserLibrary`, ...) and re-exports everything here for convenience —
 * but it also imports `getApiClient()` from `@/lib/auth/session`, which
 * starts with `import "server-only"`. Importing `./library.ts` from a Client
 * Component bundle fails at build/test time through that transitive import
 * even for symbols (like these) that don't themselves touch the network —
 * same split rationale as `./catalog-types.ts` vs `./catalog.ts`.
 */

export type LibraryStatusValue = components["schemas"]["LibraryStatus"];

export const LIBRARY_STATUSES: readonly LibraryStatusValue[] = [
  "want",
  "in_progress",
  "completed",
  "dropped",
];

export function isLibraryStatus(value: string): value is LibraryStatusValue {
  return (LIBRARY_STATUSES as readonly string[]).includes(value);
}

/** A single `/u/{username}/library` (FE-20) entry — `GET /v1/users/{username}/library`'s per-item shape. */
export type LibraryEntry = components["schemas"]["LibraryEntryOut"];

/**
 * Sort order for `/u/{username}/library` (FE-38), same `?sort=` convention
 * as `CatalogSort` (`./catalog-types.ts`, FE-9 browse) but a distinct union:
 * the backend's `GET /v1/users/{username}/library` has no `sort` query
 * param at all (`docs/api.md` — it's always reverse-chronological by
 * `created_at`), so every value here is applied client-side, in
 * `sortLibraryEntries` below, over the single already-fetched page of
 * entries rather than as a request parameter. That's also why this can't
 * just reuse `CatalogSort`: `updated_desc` has no browse equivalent (it
 * reads `LibraryEntryOut.updated_at`, already present on every entry), and
 * `rating_desc` means "the library owner's own score for that item" (see
 * {@link reviewScoreKey}'s doc comment), not `rating_external`.
 */
export type LibrarySort = "updated_desc" | "rating_desc" | "title_asc" | "date_desc";

export const LIBRARY_SORTS: readonly LibrarySort[] = [
  "updated_desc",
  "rating_desc",
  "title_asc",
  "date_desc",
];

export const DEFAULT_LIBRARY_SORT: LibrarySort = "updated_desc";

export function isLibrarySort(value: string): value is LibrarySort {
  return (LIBRARY_SORTS as readonly string[]).includes(value);
}

/**
 * Lookup key shared by {@link sortLibraryEntries}'s `rating_desc` branch and
 * `./library.ts`'s `getUserReviewScores` — both need to match a
 * `LibraryEntry` (`item.item_type`/`item.slug`, e.g. `"MOVIE"`/`"dune-2021"`)
 * against a `UserReviewOut` (`item.item_type`/`item.slug`, same casing
 * convention per the backend's UNION ALL rows) for the same underlying item.
 * `.toUpperCase()` on both sides guards against the two endpoints ever
 * drifting on casing.
 */
export function reviewScoreKey(itemType: string, slug: string): string {
  return `${itemType.toUpperCase()}:${slug}`;
}

/**
 * Descending comparator for nullable ISO date strings (`YYYY-MM-DD` or
 * `YYYY-MM-DDTHH:mm:ssZ` — lexicographic order matches chronological order
 * for both, no `Date` parsing needed). Missing dates always sort last,
 * regardless of direction, rather than being treated as `""` (which would
 * otherwise sort first under plain string comparison).
 */
function compareNullableIsoDatesDesc(a: string | null, b: string | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a < b ? 1 : a > b ? -1 : 0;
}

/**
 * Applies a {@link LibrarySort} to one already-fetched page of
 * `/u/{username}/library` entries (FE-38) — pure and synchronous, no
 * network calls, so `page.tsx` can call it directly after `getUserLibrary`
 * resolves. Only reorders the entries it's given; see this module's
 * `LibrarySort` doc comment for why a page's worth of entries (not the
 * user's whole library) is the unit being sorted.
 *
 * `scores` (the library owner's own rating per item, keyed by
 * {@link reviewScoreKey}) is only consulted for `rating_desc` and is
 * optional elsewhere — callers only fetch it (`getUserReviewScores`) when
 * `sort === "rating_desc"`, to avoid an extra request on every page load.
 * Entries with no score (rated `null`, or missing from `scores` entirely —
 * e.g. it fell outside `getUserReviewScores`'s scan, see that function's
 * doc comment) always sort last, same "missing sorts last" rule as
 * {@link compareNullableIsoDatesDesc}.
 */
export function sortLibraryEntries(
  entries: LibraryEntry[],
  sort: LibrarySort,
  scores?: Map<string, number>,
): LibraryEntry[] {
  const sorted = [...entries];

  switch (sort) {
    case "title_asc":
      sorted.sort((a, b) => a.item.title.localeCompare(b.item.title));
      break;
    case "date_desc":
      sorted.sort((a, b) => compareNullableIsoDatesDesc(a.item.release_date, b.item.release_date));
      break;
    case "rating_desc": {
      const scoreOf = (entry: LibraryEntry): number | null =>
        scores?.get(reviewScoreKey(entry.item.item_type, entry.item.slug)) ?? null;
      sorted.sort((a, b) => {
        const scoreA = scoreOf(a);
        const scoreB = scoreOf(b);
        if (scoreA === null && scoreB === null) return 0;
        if (scoreA === null) return 1;
        if (scoreB === null) return -1;
        return scoreB - scoreA;
      });
      break;
    }
    case "updated_desc":
      sorted.sort((a, b) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0));
      break;
  }

  return sorted;
}

/**
 * Tailwind classes for each status's design-system color pair (FE-37,
 * `--status-<status>`/`--status-<status>-foreground` in `globals.css`).
 * Centralized here so the three call sites that need a status color —
 * `ViewerStatusSlot`'s active status button, `StatusTabs`'s active tab
 * (`/u/[username]/library/page.tsx`), and `CatalogCard`'s library badge —
 * stay in sync instead of each hardcoding the class names (and the
 * `in_progress` -> `in-progress` CSS variable naming, since Tailwind v4
 * utility names are kebab-case while `LibraryStatusValue` is snake_case).
 */
export const STATUS_COLOR_CLASSES: Record<LibraryStatusValue, string> = {
  want: "bg-status-want text-status-want-foreground hover:bg-status-want/80",
  in_progress:
    "bg-status-in-progress text-status-in-progress-foreground hover:bg-status-in-progress/80",
  completed: "bg-status-completed text-status-completed-foreground hover:bg-status-completed/80",
  dropped: "bg-status-dropped text-status-dropped-foreground hover:bg-status-dropped/80",
};

/**
 * `!`-prefixed (Tailwind's `important` modifier) mirror of
 * `STATUS_COLOR_CLASSES`, for uses that layer the status color on top of a
 * shadcn `Button` `variant` (FE-37 bugfix, `ViewerStatusSlot`'s active
 * status button). `Button`'s `variant="outline"` (`ui/button.tsx`) carries
 * `dark:border-input dark:bg-input/30 dark:hover:bg-input/50`; this
 * project's `@custom-variant dark (&:is(.dark *))` (`globals.css`) compiles
 * those `dark:*` classes to selectors with an extra `:is(...)` pseudo-class,
 * which out-specifies the plain `bg-status-<x>`/`border-transparent`
 * utilities `STATUS_COLOR_CLASSES` produces. In dark theme that lets the
 * variant's own gray `--input` background win the cascade over the status
 * color; in light theme `dark:*` never matches (no `.dark` ancestor), so
 * there's nothing to out-specify and the color shows correctly — which is
 * exactly why the bug only reproduced in dark theme. `!important` sidesteps
 * the specificity race outright instead of trying to out-rank it, so the fix
 * doesn't depend on Tailwind's utility-generation order, which could change
 * (and re-break this) in a future Tailwind upgrade.
 *
 * Intentionally hand-written literal strings rather than derived from
 * `STATUS_COLOR_CLASSES` at runtime (e.g. via `.replace()`): Tailwind v4's
 * JIT compiler generates CSS only for class names that appear as literal
 * substrings somewhere in the scanned source files. A class name built by
 * string concatenation/regex at runtime never exists as literal text in any
 * `.ts`/`.tsx` file, so the scanner can't find it and silently never
 * generates the corresponding `!important` rule — confirmed by hand while
 * building this fix (a `.replace()`-derived version produced the right
 * runtime class list but an unstyled button, since the CSS for e.g.
 * `!bg-status-want` was never emitted). Every class below must stay a
 * literal string for that reason.
 */
export const STATUS_COLOR_CLASSES_IMPORTANT: Record<LibraryStatusValue, string> = {
  want: "!bg-status-want !text-status-want-foreground hover:!bg-status-want/80",
  in_progress:
    "!bg-status-in-progress !text-status-in-progress-foreground hover:!bg-status-in-progress/80",
  completed:
    "!bg-status-completed !text-status-completed-foreground hover:!bg-status-completed/80",
  dropped: "!bg-status-dropped !text-status-dropped-foreground hover:!bg-status-dropped/80",
};
