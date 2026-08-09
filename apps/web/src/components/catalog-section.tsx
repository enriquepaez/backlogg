import type { ReactNode } from "react";

import { Link } from "@/i18n/navigation";

export type CatalogSectionProps = {
  heading: string;
  /** Whether the section has no items to show — renders `emptyMessage` instead of `children`. */
  isEmpty: boolean;
  emptyMessage: string;
  /** Rendered `CatalogCard`s (or any grid content) for the non-empty state. */
  children: ReactNode;
  /** Optional "view all" link (e.g. `/browse/{type}`), omitted for sections without one. */
  viewAllHref?: string;
  viewAllLabel?: string;
};

/**
 * Shared layout for the home page's catalog sections (trending + one per
 * type): a heading with an optional "view all" link, and either a
 * responsive poster grid or an empty-state message. Purely presentational —
 * data fetching and degradation live in `src/lib/catalog.ts`.
 */
export function CatalogSection({
  heading,
  isEmpty,
  emptyMessage,
  children,
  viewAllHref,
  viewAllLabel,
}: CatalogSectionProps) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-medium">{heading}</h2>
        {viewAllHref && viewAllLabel ? (
          <Link
            href={viewAllHref}
            className="text-sm font-medium text-primary hover:underline"
          >
            {viewAllLabel}
          </Link>
        ) : null}
      </div>
      {isEmpty ? (
        <p className="text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {children}
        </div>
      )}
    </section>
  );
}
