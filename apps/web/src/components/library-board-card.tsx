import { ImageOff } from "lucide-react";
import Image from "next/image";

import { Link } from "@/i18n/navigation";

export type LibraryBoardCardProps = {
  title: string;
  posterUrl: string | null;
  /** Item detail page path, same optional-`href` convention as `CatalogCard`. */
  href?: string;
};

/**
 * Compact poster+title card for the library board view (FE-43) —
 * deliberately smaller and plainer than `CatalogCard` (no rating/type/status
 * badges): a board column's colored header already conveys the status every
 * card in it shares, and a board is meant to be scanned as a dense list, not
 * as a showcase grid. Renders as a plain `<div>` when `href` is omitted, same
 * defensive fallback as `CatalogCard` for an `item_type` that doesn't map to
 * a known `CatalogType` — practically unreachable given the backend's fixed
 * `LibraryEntryOut.item.item_type` values, but kept for symmetry.
 */
export function LibraryBoardCard({ title, posterUrl, href }: LibraryBoardCardProps) {
  const card = (
    <div className="flex items-center gap-2 rounded-md bg-card p-1.5 ring-1 ring-foreground/10">
      <div className="relative h-14 w-10 shrink-0 overflow-hidden rounded bg-muted">
        {posterUrl ? (
          <Image src={posterUrl} alt="" fill sizes="40px" className="object-cover" />
        ) : (
          <div role="img" aria-label={title} className="flex h-full w-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden className="size-4" />
          </div>
        )}
      </div>
      <p className="line-clamp-2 text-xs font-medium" title={title}>
        {title}
      </p>
    </div>
  );

  if (!href) {
    return card;
  }

  return (
    <Link
      href={href}
      className="block rounded-md outline-none transition-opacity hover:opacity-90 focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {card}
    </Link>
  );
}
