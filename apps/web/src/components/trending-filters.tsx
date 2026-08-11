"use client";

import { useTranslations } from "next-intl";

import { useRouter } from "@/i18n/navigation";
import {
  DEFAULT_TRENDING_PERIOD,
  TRENDING_PERIODS,
  TRENDING_TYPES,
  type TrendingPeriod,
  type TrendingType,
} from "@/lib/catalog-types";

export type TrendingFiltersProps = {
  selectedType?: TrendingType;
  selectedPeriod: TrendingPeriod;
};

// Same rationale as `BrowseFilters`' `SELECT_CLASSNAME`/`OPTION_CLASSNAME` (FE-9).
const SELECT_CLASSNAME =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2.5 py-1 text-base text-foreground transition-colors outline-none [color-scheme:light] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:[color-scheme:dark] dark:bg-input/30";
const OPTION_CLASSNAME = "bg-background text-foreground";

/**
 * Type + period filter controls for `/trending` (FE-12), same navigate-on-
 * change pattern as `BrowseFilters` (FE-9): every change goes through
 * `router.replace` with an explicit `{ pathname, query }` href (never merged
 * partially from the previous value), so `/trending?type=movie&period=day`
 * stays shareable and clearing a filter can't be confused with "untouched".
 * `period` is omitted from the query when it's the default (`week`), mirroring
 * how `BrowseFilters` omits `sort` when it's `DEFAULT_CATALOG_SORT`.
 */
export function TrendingFilters({ selectedType, selectedPeriod }: TrendingFiltersProps) {
  const router = useRouter();
  const t = useTranslations("Trending.filters");

  function navigate({ type, period }: { type?: TrendingType; period: TrendingPeriod }) {
    const query: Record<string, string> = {};
    if (type) {
      query.type = type;
    }
    if (period !== DEFAULT_TRENDING_PERIOD) {
      query.period = period;
    }
    router.replace({ pathname: "/trending", query });
  }

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="trending-type" className="text-sm font-medium">
          {t("typeLabel")}
        </label>
        <select
          id="trending-type"
          className={SELECT_CLASSNAME}
          value={selectedType ?? ""}
          onChange={(event) =>
            navigate({
              type: (event.target.value || undefined) as TrendingType | undefined,
              period: selectedPeriod,
            })
          }
        >
          <option value="" className={OPTION_CLASSNAME}>
            {t("all")}
          </option>
          {TRENDING_TYPES.map((type) => (
            <option key={type} value={type} className={OPTION_CLASSNAME}>
              {t(type)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="trending-period" className="text-sm font-medium">
          {t("periodLabel")}
        </label>
        <select
          id="trending-period"
          className={SELECT_CLASSNAME}
          value={selectedPeriod}
          onChange={(event) =>
            navigate({ type: selectedType, period: event.target.value as TrendingPeriod })
          }
        >
          {TRENDING_PERIODS.map((period) => (
            <option key={period} value={period} className={OPTION_CLASSNAME}>
              {t(`period.${period}`)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
