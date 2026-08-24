"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Loader2, SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useRouter } from "@/i18n/navigation";
import { CATALOG_TYPES, type CatalogType } from "@/lib/catalog-types";

export type SearchControlsProps = {
  /** Current `q` from the URL — the single source of truth this component debounces edits against. */
  initialQuery: string;
  initialType?: CatalogType;
  /**
   * Re-scope of FE-35 (`browse_search_filters`): date-range and
   * external-rating-range filters, currently applied from the URL. Mirrors
   * `AdminCatalogFiltersProps`' equivalent fields minus the rating-internal
   * pair — `GET /v1/search` (backed by the `catalog_search` view, which has
   * no `rating_internal` column) doesn't support it.
   */
  initialDateFrom?: string;
  initialDateTo?: string;
  initialRatingExternalMin?: number;
  initialRatingExternalMax?: number;
};

/**
 * Wait this long after the user stops typing before pushing `q` to the URL.
 * No precedent elsewhere in the repo (FE-9's filters navigate immediately on
 * `onChange` since a `<select>` change is already a deliberate, discrete
 * action) — a free-text input firing one navigation (and one `/v1/search`
 * request) per keystroke would be wasteful and, worse, would burn through
 * the backend's per-IP external-fallback rate limit on the very sequence of
 * queries transitioning to the user's final, complete word.
 */
const DEBOUNCE_MS = 400;

/**
 * Debounce window for the advanced filters (date range, external-rating
 * range) — same value and rationale as `AdminCatalogFilters`' equivalent
 * group: a discrete typed value shouldn't fire one navigation per keystroke,
 * but there's no external-fallback rate-limit concern here (unlike `q`)
 * driving a longer window.
 */
const FILTER_DEBOUNCE_MS = 300;

const SELECT_CLASSNAME =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2.5 py-1 text-base text-foreground transition-colors outline-none [color-scheme:light] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:[color-scheme:dark] dark:bg-input/30";
const OPTION_CLASSNAME = "bg-background text-foreground";

type AdvancedFields = {
  dateFrom?: string;
  dateTo?: string;
  ratingExternalMin?: number;
  ratingExternalMax?: number;
};

function toInputValue(value: number | undefined): string {
  return value === undefined ? "" : String(value);
}

function parseRatingInput(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function buildQuery(
  q: string,
  type: CatalogType | undefined,
  advanced: AdvancedFields,
): Record<string, string> {
  const query: Record<string, string> = {};
  if (q) query.q = q;
  if (type) query.type = type;
  if (advanced.dateFrom) query.date_from = advanced.dateFrom;
  if (advanced.dateTo) query.date_to = advanced.dateTo;
  if (advanced.ratingExternalMin !== undefined) query.rating_external_min = String(advanced.ratingExternalMin);
  if (advanced.ratingExternalMax !== undefined) query.rating_external_max = String(advanced.ratingExternalMax);
  return query;
}

/**
 * Search input (debounced) + type filter, plus (re-scope of FE-35,
 * `browse_search_filters`) a date-range and external-rating-range "More
 * filters" popover, for `/search` (FE-11). A client component because
 * typing needs local, instantaneous input state — but, like `BrowseFilters`
 * (FE-9) and `AdminCatalogFilters` (FE-34), the actual state lives in the
 * URL: every committed change goes through `router.replace({ pathname,
 * query })`, so `/search?q=...&type=...&date_from=...` stays shareable and
 * the page's Server Component re-fetches on every change.
 *
 * `q`'s own debounce/sync logic is unchanged from before this re-scope (see
 * `progress/current.md`: "no lo toques salvo lo estrictamente necesario para
 * integrarlo") — the only change is that {@link navigate} (called by the `q`
 * debounce effect, the type `<select>`'s immediate `onChange`, and the
 * advanced-filters debounce effect alike) now always includes the current
 * pending advanced-filter values too, so none of the three triggers ever
 * clobbers the other two's in-flight edits.
 *
 * The advanced filters (date range, external-rating range) follow the exact
 * pattern `AdminCatalogFilters` established (debounced local state, "adjust
 * state during render" resync to the URL, client-side range validation that
 * never sends an invalid pair — falls back to the last committed value for
 * that pair instead, with an inline `role="alert"` message) minus the
 * rating-internal group, which `/search` doesn't support.
 */
export function SearchControls({
  initialQuery,
  initialType,
  initialDateFrom,
  initialDateTo,
  initialRatingExternalMin,
  initialRatingExternalMax,
}: SearchControlsProps) {
  const router = useRouter();
  const t = useTranslations("Search");
  const [value, setValue] = useState(initialQuery);

  // `router.replace` here is imperative (debounced typing, the type
  // `<select>`, the advanced filters), not a `<Link>` click — `useLinkStatus`
  // (used by `SearchPagination`'s prev/next `Link`s) doesn't apply to it, so
  // there was previously no feedback at all while a new query (or the first
  // query, which can hit the external fan-out — `backlogg/search/service.py`)
  // was in flight. `useTransition` is React's mechanism for exactly this:
  // pending state around a navigation triggered outside a `Link`.
  const [isPending, startTransition] = useTransition();

  // The URL is the source of truth: if it changes underneath us (filter
  // change, pagination, back/forward, or a shared link), sync the visible
  // input to match rather than let it drift. Adjusted during render (React's
  // documented "store the previous prop and compare" pattern) instead of in
  // an effect, so this doesn't fire a redundant extra render on every prop
  // change (see https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes).
  const [syncedQuery, setSyncedQuery] = useState(initialQuery);
  if (initialQuery !== syncedQuery) {
    setSyncedQuery(initialQuery);
    setValue(initialQuery);
  }

  const [dateFromInput, setDateFromInput] = useState(initialDateFrom ?? "");
  const [dateToInput, setDateToInput] = useState(initialDateTo ?? "");
  const [ratingExternalMinInput, setRatingExternalMinInput] = useState(toInputValue(initialRatingExternalMin));
  const [ratingExternalMaxInput, setRatingExternalMaxInput] = useState(toInputValue(initialRatingExternalMax));

  // Same "adjust state during render" resync as `q` above, but for the four
  // advanced fields together — one combined signature so a change to any of
  // them (for a reason other than this component's own pending edit) resets
  // all four local inputs back to the URL's current values in one go.
  const advancedCommittedKey = JSON.stringify([
    initialDateFrom,
    initialDateTo,
    initialRatingExternalMin,
    initialRatingExternalMax,
  ]);
  const [syncedAdvancedKey, setSyncedAdvancedKey] = useState(advancedCommittedKey);
  if (advancedCommittedKey !== syncedAdvancedKey) {
    setSyncedAdvancedKey(advancedCommittedKey);
    setDateFromInput(initialDateFrom ?? "");
    setDateToInput(initialDateTo ?? "");
    setRatingExternalMinInput(toInputValue(initialRatingExternalMin));
    setRatingExternalMaxInput(toInputValue(initialRatingExternalMax));
  }

  const dateRangeInvalid = dateFromInput !== "" && dateToInput !== "" && dateFromInput > dateToInput;

  const ratingExternalMinValue = parseRatingInput(ratingExternalMinInput);
  const ratingExternalMaxValue = parseRatingInput(ratingExternalMaxInput);
  const ratingExternalRangeInvalid =
    ratingExternalMinValue !== undefined &&
    ratingExternalMaxValue !== undefined &&
    ratingExternalMinValue > ratingExternalMaxValue;

  // If a pair is currently invalid, its pending edit is not sent — falls
  // back to the last-known-valid committed value instead (same rule
  // `AdminCatalogFilters` follows), so an unrelated change (e.g. `q`, type,
  // or the *other* range) can still navigate while the user fixes this one.
  const pendingAdvanced: AdvancedFields = {
    dateFrom: dateRangeInvalid ? initialDateFrom : dateFromInput || undefined,
    dateTo: dateRangeInvalid ? initialDateTo : dateToInput || undefined,
    ratingExternalMin: ratingExternalRangeInvalid ? initialRatingExternalMin : ratingExternalMinValue,
    ratingExternalMax: ratingExternalRangeInvalid ? initialRatingExternalMax : ratingExternalMaxValue,
  };
  const committedAdvanced: AdvancedFields = {
    dateFrom: initialDateFrom,
    dateTo: initialDateTo,
    ratingExternalMin: initialRatingExternalMin,
    ratingExternalMax: initialRatingExternalMax,
  };
  const pendingAdvancedKey = JSON.stringify(pendingAdvanced);
  const committedAdvancedKey = JSON.stringify(committedAdvanced);

  function navigate({ q, type }: { q: string; type?: CatalogType }) {
    startTransition(() => {
      router.replace({ pathname: "/search", query: buildQuery(q, type, pendingAdvanced) });
    });
  }

  useEffect(() => {
    const trimmed = value.trim();
    if (trimmed === initialQuery) {
      return;
    }
    const handle = setTimeout(() => {
      navigate({ q: trimmed, type: initialType });
    }, DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // Only re-run when the pending value itself changes — `initialType` and
    // `initialQuery` are read fresh inside the closure but must not, by
    // themselves, restart the debounce window while the user is still typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // Set by `handleClearAdvancedFilters` right before it resets the four
  // local fields (see below) so the very next run of the effect below —
  // triggered by that same reset changing `pendingAdvancedKey` — is skipped
  // instead of scheduling a stale, redundant navigation.
  const skipNextAdvancedDebounceRef = useRef(false);

  useEffect(() => {
    if (skipNextAdvancedDebounceRef.current) {
      skipNextAdvancedDebounceRef.current = false;
      return;
    }
    if (pendingAdvancedKey === committedAdvancedKey) return;
    const handle = setTimeout(() => {
      navigate({ q: value.trim(), type: initialType });
    }, FILTER_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // Only the pending advanced values themselves should restart this
    // debounce window — everything else is read fresh inside the closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAdvancedKey]);

  function handleClearAdvancedFilters() {
    skipNextAdvancedDebounceRef.current = true;
    setDateFromInput("");
    setDateToInput("");
    setRatingExternalMinInput("");
    setRatingExternalMaxInput("");
    startTransition(() => {
      router.replace({
        pathname: "/search",
        query: buildQuery(value.trim(), initialType, {}),
      });
    });
  }

  const dateGroupActive = dateFromInput !== "" || dateToInput !== "";
  const ratingExternalGroupActive =
    ratingExternalMinInput.trim() !== "" || ratingExternalMaxInput.trim() !== "";
  const advancedFilterCount = [dateGroupActive, ratingExternalGroupActive].filter(Boolean).length;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex min-w-48 flex-1 flex-col gap-1">
          <label htmlFor="search-q" className="text-sm font-medium">
            {t("inputLabel")}
          </label>
          <Input
            id="search-q"
            type="search"
            placeholder={t("placeholder")}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="search-type" className="text-sm font-medium">
            {t("filters.typeLabel")}
          </label>
          <select
            id="search-type"
            className={SELECT_CLASSNAME}
            value={initialType ?? ""}
            onChange={(event) =>
              navigate({
                q: value.trim(),
                type: (event.target.value || undefined) as CatalogType | undefined,
              })
            }
          >
            <option value="" className={OPTION_CLASSNAME}>
              {t("filters.all")}
            </option>
            {CATALOG_TYPES.map((type) => (
              <option key={type} value={type} className={OPTION_CLASSNAME}>
                {t(`filters.${type}`)}
              </option>
            ))}
          </select>
        </div>

        <Popover>
          <PopoverTrigger asChild>
            <Button type="button" variant="outline" size="sm" className="h-9 gap-1.5">
              <SlidersHorizontal className="h-4 w-4" />
              {t("filters.moreFilters")}
              {advancedFilterCount > 0 ? (
                <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-xs text-primary-foreground">
                  {advancedFilterCount}
                </span>
              ) : null}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80 p-4">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <div className="flex items-end gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="search-date-from">{t("filters.dateFromLabel")}</Label>
                    <Input
                      id="search-date-from"
                      type="date"
                      className="w-36"
                      value={dateFromInput}
                      onChange={(event) => setDateFromInput(event.target.value)}
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="search-date-to">{t("filters.dateToLabel")}</Label>
                    <Input
                      id="search-date-to"
                      type="date"
                      className="w-36"
                      value={dateToInput}
                      onChange={(event) => setDateToInput(event.target.value)}
                    />
                  </div>
                </div>

                {dateRangeInvalid ? (
                  <p role="alert" className="text-xs text-destructive">
                    {t("filters.dateRangeInvalid")}
                  </p>
                ) : null}
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-end gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="search-rating-external-min">
                      {t("filters.ratingExternalMinLabel")}
                    </Label>
                    <Input
                      id="search-rating-external-min"
                      type="number"
                      step="0.1"
                      className="w-24"
                      value={ratingExternalMinInput}
                      onChange={(event) => setRatingExternalMinInput(event.target.value)}
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="search-rating-external-max">
                      {t("filters.ratingExternalMaxLabel")}
                    </Label>
                    <Input
                      id="search-rating-external-max"
                      type="number"
                      step="0.1"
                      className="w-24"
                      value={ratingExternalMaxInput}
                      onChange={(event) => setRatingExternalMaxInput(event.target.value)}
                    />
                  </div>
                </div>

                {ratingExternalRangeInvalid ? (
                  <p role="alert" className="text-xs text-destructive">
                    {t("filters.ratingExternalRangeInvalid")}
                  </p>
                ) : null}
              </div>

              {advancedFilterCount > 0 ? (
                <Button type="button" variant="ghost" size="sm" onClick={handleClearAdvancedFilters}>
                  {t("filters.clearFilters")}
                </Button>
              ) : null}
            </div>
          </PopoverContent>
        </Popover>
      </div>

      {/*
       * Fixed line-height reserved regardless of `isPending` (same "reserve
       * space, toggle content" approach as `SearchPaginationStatus`) so the
       * results grid below doesn't jump when this appears/disappears.
       */}
      <p
        role="status"
        aria-live="polite"
        className="flex min-h-4 items-center gap-1.5 text-xs text-muted-foreground"
      >
        {isPending ? (
          <>
            <Loader2 className="size-3 animate-spin" aria-hidden="true" />
            {t("searching")}
          </>
        ) : (
          ""
        )}
      </p>
    </div>
  );
}
