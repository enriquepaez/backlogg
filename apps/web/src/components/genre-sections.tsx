import { Link } from "@/i18n/navigation";
import { CATALOG_TYPES, type CatalogType, type GenreWithType } from "@/lib/catalog-types";

export type GenreSectionsProps = {
  genres: GenreWithType[];
  /** When set, `genres` are all of this one type — renders a single, unlabelled section instead of one per type. */
  selectedType?: CatalogType;
  /** Localized section headings, keyed by type (reuses `Browse.heading` — see `[locale]/genres/page.tsx`). */
  typeLabels: Record<CatalogType, string>;
};

function genresForType(genres: GenreWithType[], type: CatalogType): GenreWithType[] {
  return genres.filter((genre) => genre.item_type === type);
}

/**
 * Renders genres grouped by content type, each linking to
 * `/browse/{item_type}?genre=slug` (FE-9's filtered list) — the `/genres`
 * page's (FE-12) main content. Grouped into one section per type (in
 * `CATALOG_TYPES` order) when `selectedType` is unset, since
 * `GET /v1/genres` without `?type=` mixes all four types together; a single
 * unlabelled section when it is set. Caller (`[locale]/genres/page.tsx`)
 * already handles the page-level empty/error states — this component assumes
 * `genres` is non-empty overall, but a specific type can still have none
 * (silently renders no section for it, same as `CatalogSection`'s
 * `viewAllHref` being optional).
 */
export function GenreSections({ genres, selectedType, typeLabels }: GenreSectionsProps) {
  const types = selectedType ? [selectedType] : CATALOG_TYPES;

  return (
    <div className="flex flex-col gap-10">
      {types.map((type) => {
        const items = genresForType(genres, type);
        if (items.length === 0) {
          return null;
        }
        return (
          <section key={type} className="flex flex-col gap-4">
            {selectedType ? null : (
              <h2 className="text-xl font-medium">{typeLabels[type]}</h2>
            )}
            <div className="flex flex-wrap gap-2">
              {items.map((genre) => (
                <Link
                  key={genre.slug}
                  href={{ pathname: `/browse/${type}`, query: { genre: genre.slug } }}
                  className="rounded-full border border-input bg-background px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
                >
                  {genre.name} ({genre.count})
                </Link>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
