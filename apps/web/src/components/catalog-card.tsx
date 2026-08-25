import { ImageOff, Star } from "lucide-react";
import Image from "next/image";
import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";
import { STATUS_COLOR_CLASSES, type LibraryStatusValue } from "@/lib/library-types";
import { cn } from "@/lib/utils";

export type CatalogCardProps = {
  /** Item title. Catalog content is never translated (see `apps/web/AGENTS.md` / i18n note). */
  title: string;
  /**
   * Release year, appended to the title as "Title (Year)" when present —
   * disambiguates grids with several items sharing the same title (e.g.
   * search results for a long-running franchise). Omitted (no parentheses
   * at all) when the caller has no year, rather than showing an empty
   * "()" — most callers pre-derive this from a type-specific date field
   * (`release_date`/`first_air_date`/`first_publish_date`) since this
   * presentational component has no notion of item type.
   */
  year?: number | null;
  posterUrl: string | null;
  /**
   * The community's own average rating (`rating_internal`, `docs/schema.md`)
   * — the only rating shown to end users (FE-59/backend `rating_display_
   * internal_only`), never `rating_external` (TMDB/Open Library/IGDB).
   * `null` until at least one user has rated the item, which is expected to
   * be common early on; the badge is simply omitted in that case rather than
   * falling back to the external rating or a placeholder.
   */
  ratingInternal: number | null;
  /**
   * Small badge over the poster (e.g. the localized type name). Used by the
   * trending grid, which mixes movies and series, to disambiguate items —
   * omitted for the per-type "featured" grids where it would be redundant.
   */
  typeLabel?: string;
  /**
   * The viewer's own backlog status for this item (FE-37), when known —
   * drives the color of the small status badge rendered over the poster
   * (bottom-left, `--status-<status>`/`--status-<status>-foreground` from
   * `globals.css`, same pair `ViewerStatusSlot`'s active button and
   * `StatusTabs`'s active tab use). Only `/u/[username]/library/page.tsx`
   * passes this today — it's the only grid whose `LibraryEntryOut` already
   * carries a `status` per item; other grids (home, browse, search, similar)
   * don't have that data per item and simply omit the prop, which omits the
   * badge (see `libraryStatusLabel` below).
   */
  libraryStatus?: LibraryStatusValue;
  /**
   * Localized text for the {@link libraryStatus} badge (e.g.
   * `Library.statusTabs.want` -> "Want"), pre-translated by the caller —
   * same house style as `typeLabel`, since this presentational component has
   * no i18n context of its own. Required whenever `libraryStatus` is set;
   * the badge is omitted if either is missing.
   */
  libraryStatusLabel?: string;
  /**
   * Item detail page path (e.g. `/movie/dune-2021`, FE-10), made available
   * once FE-10 shipped a route to link to. When omitted the card renders as
   * a plain, non-interactive tile — used by contexts that don't (yet) have
   * anywhere to send the click.
   */
  href?: string;
  /**
   * Optional extra content rendered below the title, inside the card (and,
   * when `href` is set, inside the same link). Used by the `/recommendations`
   * grid (FE-27) to surface each result's `reason` (e.g. "Because you rated
   * Dune") without duplicating the poster/title/rating markup in a parallel
   * component.
   */
  footer?: ReactNode;
};

/**
 * Presentational poster card shared by the home page's trending and
 * "featured" sections (FE-8), the `/browse/{type}` grid (FE-9), and the item
 * detail page's "similar" section (FE-10). Wrapped in a `Link` to
 * `/{type}/{slug}` whenever a caller passes `href`.
 */
export function CatalogCard({
  title,
  year,
  posterUrl,
  ratingInternal,
  typeLabel,
  libraryStatus,
  libraryStatusLabel,
  href,
  footer,
}: CatalogCardProps) {
  const displayTitle = year ? `${title} (${year})` : title;
  const card = (
    <Card size="sm" className="w-full">
      <div className="relative aspect-2/3 w-full bg-muted">
        {posterUrl ? (
          <Image
            src={posterUrl}
            alt={displayTitle}
            fill
            sizes="(max-width: 640px) 45vw, (max-width: 1024px) 22vw, 180px"
            className="object-cover"
          />
        ) : (
          <div
            role="img"
            aria-label={displayTitle}
            className="flex h-full w-full items-center justify-center text-muted-foreground"
          >
            <ImageOff aria-hidden className="size-8" />
          </div>
        )}
        {typeLabel ? (
          <span className="absolute left-2 top-2 rounded-md bg-background/90 px-1.5 py-0.5 text-xs font-medium text-foreground shadow-sm">
            {typeLabel}
          </span>
        ) : null}
        {ratingInternal != null ? (
          <span className="absolute right-2 top-2 flex items-center gap-1 rounded-md bg-background/90 px-1.5 py-0.5 text-xs font-medium text-foreground shadow-sm">
            <Star aria-hidden className="size-3 fill-current" />
            {ratingInternal.toFixed(1)}
          </span>
        ) : null}
        {libraryStatus && libraryStatusLabel ? (
          <span
            className={cn(
              "absolute bottom-2 left-2 rounded-md px-2.5 py-1 text-sm font-semibold shadow-sm",
              STATUS_COLOR_CLASSES[libraryStatus],
            )}
          >
            {libraryStatusLabel}
          </span>
        ) : null}
      </div>
      <CardContent>
        {/*
         * `min-h-10` reserves space for exactly 2 lines of `text-sm`
         * (Tailwind v4 default: font-size 0.875rem, line-height
         * calc(1.25 / 0.875) = 1.25rem/line -> 2 * 1.25rem = 2.5rem =
         * min-h-10), so 1-line and 2-line titles produce the same card
         * height across a grid (issue #12) while `line-clamp-2` still
         * truncates longer titles.
         */}
        <p className="line-clamp-2 min-h-10 text-sm font-medium" title={displayTitle}>
          {displayTitle}
        </p>
        {footer}
      </CardContent>
    </Card>
  );

  if (!href) {
    return card;
  }

  return (
    <Link
      href={href}
      className="block rounded-xl outline-none transition-opacity hover:opacity-90 focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {card}
    </Link>
  );
}
