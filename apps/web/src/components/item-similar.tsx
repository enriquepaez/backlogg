import { CatalogCard } from "@/components/catalog-card";
import type { CatalogType } from "@/lib/catalog-types";

export type ItemSimilarItem = {
  /**
   * **This result's own catalog type** — not the type of the page the
   * section is rendered on. It drives both the card's link
   * (`/{type}/{slug}`) and its colored type badge (`TYPE_COLOR_CLASSES`,
   * FE-57, applied by {@link CatalogCard}).
   *
   * It is a {@link CatalogType}, never a raw backend `item_type` string:
   * `@/lib/catalog`'s `getSimilarItems` puts every row through
   * `toCatalogType` and drops what doesn't map, so nothing un-guarded can
   * reach this component in the first place (issues #32/#33/#36 were all a
   * guessed or cast `item_type` producing a silently wrong link).
   */
  type: CatalogType;
  title: string;
  slug: string;
  poster_url: string | null;
  release_date: string | null;
  rating_internal: number | null;
};

export type ItemSimilarProps = {
  items: ItemSimilarItem[];
  heading: string;
  emptyMessage: string;
  /**
   * Localized singular type name per catalog type (`Home.typeBadge.*`, e.g.
   * "Película"/"Movie") for each card's type badge (FE-57) — pre-translated
   * by the page, same house style as `heading`/`emptyMessage` since this
   * component has no i18n context of its own.
   *
   * A whole `Record` rather than the single string this prop used to be
   * (FE-57, back when every result shared the page's type): with
   * `SIMILAR_CROSS_TYPE_QUOTA` on, this grid genuinely mixes types, exactly
   * like `ItemRelatedWorks`' does.
   */
  typeLabels: Record<CatalogType, string>;
};

/**
 * "Similar" section for the item detail page (FE-10 acceptance: "Sección
 * 'similar' ... para movies/series"; extended to book/game by FE-32). Reuses
 * `CatalogCard` (FE-8/FE-9) with an `href` to each similar item's own detail
 * page, so this doubles as a primary discovery path into other item detail
 * pages. Purely presentational, like `CatalogCard`/`CatalogSection` —
 * `heading`/`emptyMessage` come pre-translated from the page.
 *
 * **Cross-type results are first-class here (FE-67).** Backend feature 80
 * rewrote the four `/similar` endpoints over one shared semantic index, and
 * `SIMILAR_CROSS_TYPE_QUOTA` (3 of 10, switched on by this feature) reserves
 * slots for neighbours of *another* type — the cross-media bridge the
 * product is built on: the series of *The Witcher* under the game, the novel
 * under the film. So the type badge and the link come from each **item's**
 * `type`, never from the page's.
 *
 * The signal is the type badge's color, `TYPE_COLOR_CLASSES` (FE-57) as
 * applied by every other grid in the app — no second visual language, no
 * separate "also in other media" block, no reordering. A cross-type result
 * sits exactly where its own score put it.
 *
 * **Nothing new appears when the backend returns no cross-type item**: the
 * grid, its heading and its empty message behave precisely as they did
 * before this feature, which is what makes turning the quota back down to 0
 * a pure backend decision that needs no frontend change.
 *
 * `reason` (`{kind, score, source}`) travels in every result and is
 * deliberately not rendered — that is FE-69, blocked on the backend ranker
 * (feature 82). It is dropped one layer up, in `getSimilarItems`, so it
 * never reaches this component (see `SimilarEntry` in `@/lib/catalog`).
 */
export function ItemSimilar({ items, heading, emptyMessage, typeLabels }: ItemSimilarProps) {
  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{heading}</h2>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {items.map((item) => (
            <CatalogCard
              // `type` is part of the key: the same slug can legitimately
              // name two different items of two different types (a film and
              // the novel it comes from routinely share one), and this grid
              // can now hold both at once.
              key={`${item.type}-${item.slug}`}
              title={item.title}
              posterUrl={item.poster_url}
              ratingInternal={item.rating_internal}
              typeLabel={typeLabels[item.type]}
              itemType={item.type}
              href={`/${item.type}/${item.slug}`}
            />
          ))}
        </div>
      )}
    </section>
  );
}
