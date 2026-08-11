"use client";

import { useTranslations } from "next-intl";

import { useRouter } from "@/i18n/navigation";
import { CATALOG_TYPES, type CatalogType } from "@/lib/catalog-types";

export type GenreFiltersProps = {
  selectedType?: CatalogType;
};

// Same rationale as `BrowseFilters`' `SELECT_CLASSNAME`/`OPTION_CLASSNAME`
// (FE-9) for pinning explicit foreground/background colors on the native
// `<select>`/`<option>` pair instead of relying on browser inheritance.
const SELECT_CLASSNAME =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2.5 py-1 text-base text-foreground transition-colors outline-none [color-scheme:light] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:[color-scheme:dark] dark:bg-input/30";
const OPTION_CLASSNAME = "bg-background text-foreground";

/**
 * Content-type filter for `/genres` (FE-12). A client component because
 * changing the select navigates immediately (no "Apply" button), same
 * pattern as `BrowseFilters` (FE-9) — the navigation itself always goes
 * through `router.replace` with a plain `{ pathname, query }` href, so the
 * resulting URL (`/genres` or `/genres?type=movie`) stays shareable.
 */
export function GenreFilters({ selectedType }: GenreFiltersProps) {
  const router = useRouter();
  const t = useTranslations("Genres.filters");

  function navigate(type?: CatalogType) {
    const query: Record<string, string> = {};
    if (type) {
      query.type = type;
    }
    router.replace({ pathname: "/genres", query });
  }

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="genres-type" className="text-sm font-medium">
        {t("typeLabel")}
      </label>
      <select
        id="genres-type"
        className={SELECT_CLASSNAME}
        value={selectedType ?? ""}
        onChange={(event) =>
          navigate((event.target.value || undefined) as CatalogType | undefined)
        }
      >
        <option value="" className={OPTION_CLASSNAME}>
          {t("all")}
        </option>
        {CATALOG_TYPES.map((type) => (
          <option key={type} value={type} className={OPTION_CLASSNAME}>
            {t(type)}
          </option>
        ))}
      </select>
    </div>
  );
}
