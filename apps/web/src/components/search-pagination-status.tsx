"use client";

import { Loader2 } from "lucide-react";
import { useLinkStatus } from "next/link";

export type SearchPaginationStatusProps = {
  label: string;
};

/**
 * Inline "searching for more results" hint for a pagination `Link` (issue
 * #14 QA follow-up): with the search fan-out now completing incomplete
 * pages via real calls to TMDB/Open Library/IGDB (`backlogg/search/service.py`),
 * a page transition can take noticeably longer than a purely local one, and
 * the only feedback was Next's dev-only route indicator (not present in
 * production, and not scoped to this page). `useLinkStatus` tracks the
 * pending state of its nearest ancestor `Link` — must be rendered as a
 * child of the `previous`/`next` `Link` in `search-pagination.tsx`, per
 * Next's docs (`app/api-reference/functions/use-link-status`).
 *
 * Absolutely positioned so it renders in the same spot (centered below the
 * nav row) regardless of which of the two links is pending, without
 * affecting the button's own layout.
 */
export function SearchPaginationStatus({ label }: SearchPaginationStatusProps) {
  const { pending } = useLinkStatus();

  return (
    <span
      role="status"
      aria-live="polite"
      className={`pointer-events-none absolute inset-x-0 top-full mt-1 flex items-center justify-center gap-1.5 text-sm text-muted-foreground transition-opacity duration-150 ${
        pending ? "opacity-100" : "opacity-0"
      }`}
    >
      {pending ? (
        <>
          <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          {label}
        </>
      ) : (
        ""
      )}
    </span>
  );
}
