"use client";

import { useTranslations } from "next-intl";

import { useRouter } from "@/i18n/navigation";
import { CATALOG_TYPES, type CatalogType } from "@/lib/catalog-types";

export type RecommendationFiltersProps = {
  selectedType?: CatalogType;
};

// Same rationale as `BrowseFilters`'/`TrendingFilters`' `SELECT_CLASSNAME`/
// `OPTION_CLASSNAME` (FE-9/FE-12).
const SELECT_CLASSNAME =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2.5 py-1 text-base text-foreground transition-colors outline-none [color-scheme:light] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:[color-scheme:dark] dark:bg-input/30";
const OPTION_CLASSNAME = "bg-background text-foreground";

/**
 * Content-type filter for `/recommendations` (FE-27), same navigate-on-change
 * pattern as `TrendingFilters` (FE-12): every change goes through
 * `router.replace` with an explicit `{ pathname, query }` href, so the
 * resulting URL stays shareable. Changing the type always resets `page`
 * back to 1 (simply omitted from the query, same as picking a fresh filter
 * on `/browse/{type}`) — the previous page number is very likely out of
 * range for the newly filtered result set.
 */
export function RecommendationFilters({ selectedType }: RecommendationFiltersProps) {
  const router = useRouter();
  const t = useTranslations("Recommendations.filters");

  function navigate(type: CatalogType | undefined) {
    const query: Record<string, string> = {};
    if (type) {
      query.type = type;
    }
    router.replace({ pathname: "/recommendations", query });
  }

  return (
    <div className="flex flex-col gap-1">
      <label htmlFor="recommendations-type" className="text-sm font-medium">
        {t("typeLabel")}
      </label>
      <select
        id="recommendations-type"
        className={SELECT_CLASSNAME}
        value={selectedType ?? ""}
        onChange={(event) => navigate((event.target.value || undefined) as CatalogType | undefined)}
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
