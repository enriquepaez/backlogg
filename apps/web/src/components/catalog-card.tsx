import { ImageOff, Star } from "lucide-react";
import Image from "next/image";
import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";

export type CatalogCardProps = {
  /** Item title. Catalog content is never translated (see `apps/web/AGENTS.md` / i18n note). */
  title: string;
  posterUrl: string | null;
  ratingExternal: number | null;
  /**
   * Small badge over the poster (e.g. the localized type name). Used by the
   * trending grid, which mixes movies and series, to disambiguate items —
   * omitted for the per-type "featured" grids where it would be redundant.
   */
  typeLabel?: string;
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
  posterUrl,
  ratingExternal,
  typeLabel,
  href,
  footer,
}: CatalogCardProps) {
  const card = (
    <Card size="sm" className="w-full">
      <div className="relative aspect-2/3 w-full bg-muted">
        {posterUrl ? (
          <Image
            src={posterUrl}
            alt={title}
            fill
            sizes="(max-width: 640px) 45vw, (max-width: 1024px) 22vw, 180px"
            className="object-cover"
          />
        ) : (
          <div
            role="img"
            aria-label={title}
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
        {ratingExternal !== null ? (
          <span className="absolute right-2 top-2 flex items-center gap-1 rounded-md bg-background/90 px-1.5 py-0.5 text-xs font-medium text-foreground shadow-sm">
            <Star aria-hidden className="size-3 fill-current" />
            {ratingExternal.toFixed(1)}
          </span>
        ) : null}
      </div>
      <CardContent>
        <p className="line-clamp-2 text-sm font-medium" title={title}>
          {title}
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
