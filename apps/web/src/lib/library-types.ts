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
