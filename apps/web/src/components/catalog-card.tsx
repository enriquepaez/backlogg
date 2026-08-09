import { ImageOff, Star } from "lucide-react";
import Image from "next/image";

import { Card, CardContent } from "@/components/ui/card";

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
};

/**
 * Presentational poster card shared by the home page's trending and
 * "featured" sections (FE-8). Deliberately not a link: FE-9/FE-10 (browse +
 * item detail) don't exist yet, and linking cards to a detail page is out of
 * scope for this feature (see `progress/current.md`).
 */
export function CatalogCard({
  title,
  posterUrl,
  ratingExternal,
  typeLabel,
}: CatalogCardProps) {
  return (
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
      </CardContent>
    </Card>
  );
}
