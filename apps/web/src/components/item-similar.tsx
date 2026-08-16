import { CatalogCard } from "@/components/catalog-card";
import type { CatalogType } from "@/lib/catalog-types";

export type ItemSimilarItem = {
  title: string;
  slug: string;
  poster_url: string | null;
  release_date: string | null;
  rating_external: number | null;
};

export type ItemSimilarProps = {
  /**
   * All four catalog types now have a `similar` endpoint (`docs/api.md`,
   * FE-32) — only used here to build each card's `href` (`/${type}/${slug}`).
   */
  type: CatalogType;
  items: ItemSimilarItem[];
  heading: string;
  emptyMessage: string;
};

/**
 * "Similar" section for the item detail page (FE-10 acceptance: "Sección
 * 'similar' ... para movies/series"; extended to book/game by FE-32). Reuses
 * `CatalogCard` (FE-8/FE-9) with an `href` to each similar item's own detail
 * page, so this doubles as a primary discovery path into other item detail
 * pages. Purely presentational, like `CatalogCard`/`CatalogSection` —
 * `heading`/`emptyMessage` come pre-translated from the page.
 */
export function ItemSimilar({ type, items, heading, emptyMessage }: ItemSimilarProps) {
  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{heading}</h2>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {items.map((item) => (
            <CatalogCard
              key={item.slug}
              title={item.title}
              posterUrl={item.poster_url}
              ratingExternal={item.rating_external}
              href={`/${type}/${item.slug}`}
            />
          ))}
        </div>
      )}
    </section>
  );
}
