import { CatalogCard } from "@/components/catalog-card";
import type { CatalogType } from "@/lib/catalog-types";
import type { RelatedWorkDirection } from "@/lib/related-work-labels";

export type ItemRelatedWork = {
  /**
   * The **related** item's own catalog type — not the type of the page this
   * section is rendered on. It drives both the link (`/{type}/{slug}`) and
   * the card's colored type badge, and it is a {@link CatalogType}, never a
   * raw backend `item_type` string: `@/lib/catalog`'s `getAdaptations` puts
   * every entry through `toCatalogType` and drops what doesn't map, so
   * nothing un-guarded can reach this component in the first place (issues
   * #32/#33/#36 were all a guessed or cast `item_type`).
   */
  type: CatalogType;
  slug: string;
  title: string;
  poster_url: string | null;
  direction: RelatedWorkDirection;
};

export type ItemRelatedWorksProps = {
  items: ItemRelatedWork[];
  heading: string;
  /**
   * Localized singular type name per catalog type (`Home.typeBadge.*`, e.g.
   * "Libro"/"Book") for each card's type badge — pre-translated by the page,
   * same house style as `heading` and as `ItemSimilar`'s `typeLabel`. A
   * whole `Record` rather than `ItemSimilar`'s single string because this
   * grid genuinely mixes types: that is the point of the section.
   */
  typeLabels: Record<CatalogType, string>;
  /**
   * Localized sentence per direction (`relatedWorkDirectionLabels` in
   * `@/lib/related-work-labels`), already interpolated by the page with the
   * title of the item the user is looking at. Required, and exhaustive over
   * both directions: an entry that rendered without its direction line would
   * be exactly the "undifferentiated list" FE-66's acceptance criteria
   * forbid, so the compiler enforces the copy exists instead of a test
   * catching it later (same reasoning as `ItemCredits`' mandatory
   * `roleLabels`).
   */
  directionLabels: Record<RelatedWorkDirection, string>;
};

/**
 * "Related works" section for the item detail page (FE-66) — the declared
 * `P144` ("based on") / `P4969` ("derivative work") edges Wikidata knows
 * about, served by `GET /v1/{type}/{slug}/adaptations` (backend features
 * 79/92).
 *
 * **One neutral section, not "Adaptations"** (the user's decision on FE-66,
 * taken from the real data): 16 of the 18 edges in the catalog are
 * `SERIES`→`SERIES`, and under *Better Call Saul* the endpoint returns
 * *Breaking Bad* and *Better Call Saul Presents: Slippin' Jimmy* — a prequel
 * and a spin-off, neither of them an adaptation. A heading promising
 * adaptations over that list would read as a bug. Cross-media entries still
 * stand out on their own, through the color of their type badge
 * (`TYPE_COLOR_CLASSES`, FE-57, applied by `CatalogCard`), with no second
 * block and no separate heading.
 *
 * The **direction travels in the text of every entry**, never in the order
 * or in the grouping: `SOURCE` means the item on the page is based on this
 * card's item, `DERIVED` means this card's item comes out of it. The backend
 * resolves the direction per entry (`docs/api.md`), and the page hands down
 * the two sentences already interpolated with the anchor item's title, so a
 * card can be read on its own without counting positions.
 *
 * **Renders nothing at all when there is nothing to show** — no heading, no
 * placeholder, unlike `ItemPlatforms` and like `ItemCredits`' filtered-empty
 * case. Most of the catalog has no edges at all (precise, low coverage by
 * design), so an empty heading would be the *common* state of this section,
 * not an edge case. The check lives in the component rather than in the
 * page's JSX because here it is intrinsic to what the section is — any
 * caller, present or future, gets the same behaviour — whereas Credits'
 * emptiness is a consequence of a filter the page itself applies.
 *
 * Reuses `CatalogCard` (like `ItemSimilar`) so an entry looks like every
 * other item tile in the app, with the direction sentence in the card's
 * `footer` slot — the same slot `/recommendations` uses for its per-item
 * `reason`. `ratingInternal` is passed `null` because the endpoint carries
 * no rating: this section is about a declared relation, not about how good
 * the related work is.
 */
export function ItemRelatedWorks({
  items,
  heading,
  typeLabels,
  directionLabels,
}: ItemRelatedWorksProps) {
  // Defensive `?? []`, same as `ItemCredits`/`ItemPlatforms`: a malformed
  // response must not take the whole page down (a `results: []` has been
  // observed reaching a sibling section as `undefined` — see
  // `progress/history.md`).
  const works = items ?? [];
  if (works.length === 0) {
    return null;
  }

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{heading}</h2>
      <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {works.map((work) => (
          <CatalogCard
            // `type` is part of the key: the same slug can legitimately name
            // two different items of two different types (a film and the
            // novel it comes from routinely share one).
            key={`${work.type}-${work.slug}`}
            title={work.title}
            posterUrl={work.poster_url}
            ratingInternal={null}
            typeLabel={typeLabels[work.type]}
            itemType={work.type}
            href={`/${work.type}/${work.slug}`}
            footer={
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                {directionLabels[work.direction]}
              </p>
            }
          />
        ))}
      </div>
    </section>
  );
}
