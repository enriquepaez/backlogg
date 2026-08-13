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
