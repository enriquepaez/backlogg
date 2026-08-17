"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Search, SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useRouter } from "@/i18n/navigation";
import { ADMIN_CATALOG_BASE_PATH } from "@/lib/admin-catalog";
import {
  CATALOG_SORTS,
  DEFAULT_CATALOG_SORT,
  type CatalogGenre,
  type CatalogSort,
  type CatalogType,
} from "@/lib/catalog-types";

export type AdminCatalogFiltersProps = {
  type: CatalogType;
  genres: CatalogGenre[];
  selectedGenre?: string;
  selectedSort: CatalogSort;
  /** Feature 50 params (`docs/api.md`), added in FE-34's post-QA second pass. All optional/independent. */
  selectedSearch?: string;
  selectedDateFrom?: string;
  selectedDateTo?: string;
  selectedRatingInternalMin?: number;
  selectedRatingInternalMax?: number;
  selectedRatingExternalMin?: number;
  selectedRatingExternalMax?: number;
};

/** Radix `Select.Item` forbids an empty-string `value` — this sentinel stands in for "no genre filter". */
const ALL_GENRES_VALUE = "__all__";

/**
 * Same debounce window as `AdminUsersDirectoryPanel`'s search field (FE-33) —
 * the pattern this feature was explicitly asked to reuse. Applied here to
 * every free-text/numeric filter (search, both date bounds, all four rating
 * bounds), not just search: a `<select>` change is already a deliberate,
 * discrete action (navigates immediately, no debounce, same as before), but
 * typing into any of these fields one keystroke at a time must not fire one
 * navigation (and one `GET /v1/{type}` request) per keystroke.
 */
const FILTER_DEBOUNCE_MS = 300;

type FilterFields = {
  search?: string;
  dateFrom?: string;
  dateTo?: string;
  ratingInternalMin?: number;
  ratingInternalMax?: number;
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

function filtersToQuery(fields: FilterFields, genre: string | undefined, sort: CatalogSort): Record<string, string> {
  const query: Record<string, string> = {};
  if (genre) query.genre = genre;
  if (sort !== DEFAULT_CATALOG_SORT) query.sort = sort;
  if (fields.search) query.search = fields.search;
  if (fields.dateFrom) query.date_from = fields.dateFrom;
  if (fields.dateTo) query.date_to = fields.dateTo;
  if (fields.ratingInternalMin !== undefined) query.rating_internal_min = String(fields.ratingInternalMin);
  if (fields.ratingInternalMax !== undefined) query.rating_internal_max = String(fields.ratingInternalMax);
  if (fields.ratingExternalMin !== undefined) query.rating_external_min = String(fields.ratingExternalMin);
  if (fields.ratingExternalMax !== undefined) query.rating_external_max = String(fields.ratingExternalMax);
  return query;
}

/**
 * Genre/sort + search/date-range/rating-range filters for
 * `/admin/{movies,series,books,games}` (FE-34, extended in a second pass
 * after the first version's manual QA: "filtros insuficientes, además debe
 * dejar buscar por nombre, fecha, rating" — feature 50, `catalog_search_filters`,
 * shipped the backend support for that request afterward).
 *
 * Genre/sort keep their original behavior exactly (immediate `router.replace`
 * on change, matching FE-9's `BrowseFilters`). The five new filters (search,
 * date range, rating-internal range, rating-external range) are local,
 * debounced input state — same URL-is-the-source-of-truth shape as
 * `SearchControls` (`/search`, FE-11): typing updates local state instantly,
 * but the actual navigation (and thus the actual `listCatalog` re-fetch) only
 * fires `FILTER_DEBOUNCE_MS` after the user stops typing, and only for a
 * value that still differs from the URL's current one. Local state resyncs
 * to the URL's props whenever they change for a reason other than this
 * component's own pending edit (a genre/sort change, pagination, or the
 * browser back button) via the same "adjust state during render" pattern
 * `SearchControls` uses instead of an extra effect.
 *
 * Client-side range validation (mirrors the backend's own `422` rule in
 * `backlogg/shared/catalog_filters.py`): if `date_from > date_to`, or either
 * rating pair's `min > max`, that pair's PENDING edit is not sent — the
 * navigation (whether from the debounce timer or an immediate genre/sort
 * change) falls back to the last-known-valid committed value for that pair
 * instead, and an inline `role="alert"` message explains why next to the
 * fields. This avoids ever intentionally sending a combination the backend is
 * documented to reject with a 422, without blocking unrelated filters (e.g.
 * genre) from still working while the user fixes the range.
 *
 * Third pass, after manual QA of the second pass's extra filters: "los
 * filtros en el admin estan bien pero son un lio. Todo esta mezclado, ademas
 * el orden es distinto a los filtros y tambien esta mezclado. Debe haber un
 * boton para eliminar todos los filtros." Addressed purely as a layout
 * reorganization plus one new action, no changes to the filtering logic
 * above:
 * - Sort is visually pulled out of the filters block into its own row (it
 *   isn't a filter), paired with the new "clear filters" button.
 * - The filters themselves are grouped into visually distinct sections,
 *   each separated by a divider.
 * - `handleClearFilters` resets every local field to empty AND navigates
 *   straight to the type's base path with an empty query — clearing genre
 *   and sort too (they're URL-sourced props, not local state, so an empty
 *   query is what resets them). It bypasses `pendingFields`/`filtersToQuery`
 *   entirely (both still carry the stale `selectedGenre`/`selectedSort` props
 *   at the moment of the click) and sets `skipNextDebounceRef` so the
 *   debounce `useEffect` — which would otherwise fire ~`FILTER_DEBOUNCE_MS`
 *   later using those same stale props and clobber this navigation — skips
 *   its next run once instead of scheduling a redundant, stale one.
 *
 * Fourth pass, after manual QA of the third pass's reorganization: "ocupan
 * demasiado" — the five groups stacked one per row pushed the table too far
 * down. Purely presentational again: the filter groups (search, genre, date
 * range, rating-internal range, rating-external range) now live in a single
 * `flex flex-wrap` row and only drop to a new line if they don't fit the
 * viewport width, instead of each always claiming a full row. Groups stay
 * visually distinct via a `border-l` divider between them (search has none,
 * being first) rather than the previous full-width `border-t` per group.
 * Each group is still one JSX node so wrapping only ever happens *between*
 * groups, never inside one (e.g. a date range's from/to pair, or its
 * validation message, always stay together).
 *
 * Fifth pass, after manual QA of the fourth pass's single-wrapping-row layout:
 * still "ocupan demasiado y desordenados" — the underlying issue was that all
 * five groups permanently claimed toolbar space regardless of how often
 * they're actually used. Rebuilt as the compact single-row toolbar pattern
 * used by shadcn/ui's own "Tasks" example (`ui.shadcn.com/examples/tasks`,
 * same Next.js + shadcn/ui + Radix stack), and mirrored by Linear/GitHub/
 * Vercel Dashboard: frequently-used filters (search, genre) stay inline as
 * compact `h-9` controls, while the less-frequent ones (date range,
 * rating-internal range, rating-external range) move into a "More filters"
 * `Popover` (new primitive, added the same way `select` was added in FE-33:
 * `pnpm dlx shadcn@latest add popover`) so they only take up space while the
 * user has actually opened it. The popover's trigger shows a small counter of
 * how many of those 3 groups currently have at least one active value, so the
 * user can tell at a glance whether advanced filters are applied without
 * opening it. Search and genre drop their separate, always-visible `<Label>`
 * in favor of a `sr-only` one (kept only so the control still has a proper
 * accessible name/`getByLabelText` target) — unlike the two adjacent,
 * identically-styled `<Select>`s FE-33 originally fixed, a text input with a
 * search icon and a genre `<Select>` showing its own selected value are not
 * visually ambiguous, so the always-visible label was pure vertical padding
 * here. `clearFilters` moves out of the sort row into the end of this
 * toolbar (still exactly `handleClearFilters`, untouched) and is now only
 * rendered when at least one filter (genre, search, or any of the 6 advanced
 * fields) is active, computed straight off the same local input state so it
 * appears/disappears the instant the user types, not after the debounce.
 * None of the state/debounce/validation/query-building logic above this
 * function changed — only how it's rendered.
 */
export function AdminCatalogFilters({
  type,
  genres,
  selectedGenre,
  selectedSort,
  selectedSearch,
  selectedDateFrom,
  selectedDateTo,
  selectedRatingInternalMin,
  selectedRatingInternalMax,
  selectedRatingExternalMin,
  selectedRatingExternalMax,
}: AdminCatalogFiltersProps) {
  const router = useRouter();
  const t = useTranslations("Admin.catalog.filters");

  const [searchInput, setSearchInput] = useState(selectedSearch ?? "");
  const [dateFromInput, setDateFromInput] = useState(selectedDateFrom ?? "");
  const [dateToInput, setDateToInput] = useState(selectedDateTo ?? "");
  const [ratingInternalMinInput, setRatingInternalMinInput] = useState(toInputValue(selectedRatingInternalMin));
  const [ratingInternalMaxInput, setRatingInternalMaxInput] = useState(toInputValue(selectedRatingInternalMax));
  const [ratingExternalMinInput, setRatingExternalMinInput] = useState(toInputValue(selectedRatingExternalMin));
  const [ratingExternalMaxInput, setRatingExternalMaxInput] = useState(toInputValue(selectedRatingExternalMax));

  // One combined signature for all seven URL-sourced values — if the URL
  // changed for a reason other than this component's own pending edit (see
  // the doc comment above), reset every local field back to it in one go.
  const committedKey = JSON.stringify([
    selectedSearch,
    selectedDateFrom,
    selectedDateTo,
    selectedRatingInternalMin,
    selectedRatingInternalMax,
    selectedRatingExternalMin,
    selectedRatingExternalMax,
  ]);
  const [syncedKey, setSyncedKey] = useState(committedKey);
  if (committedKey !== syncedKey) {
    setSyncedKey(committedKey);
    setSearchInput(selectedSearch ?? "");
    setDateFromInput(selectedDateFrom ?? "");
    setDateToInput(selectedDateTo ?? "");
    setRatingInternalMinInput(toInputValue(selectedRatingInternalMin));
    setRatingInternalMaxInput(toInputValue(selectedRatingInternalMax));
    setRatingExternalMinInput(toInputValue(selectedRatingExternalMin));
    setRatingExternalMaxInput(toInputValue(selectedRatingExternalMax));
  }

  const dateRangeInvalid = dateFromInput !== "" && dateToInput !== "" && dateFromInput > dateToInput;

  const ratingInternalMinValue = parseRatingInput(ratingInternalMinInput);
  const ratingInternalMaxValue = parseRatingInput(ratingInternalMaxInput);
  const ratingInternalRangeInvalid =
    ratingInternalMinValue !== undefined &&
    ratingInternalMaxValue !== undefined &&
    ratingInternalMinValue > ratingInternalMaxValue;

  const ratingExternalMinValue = parseRatingInput(ratingExternalMinInput);
  const ratingExternalMaxValue = parseRatingInput(ratingExternalMaxInput);
  const ratingExternalRangeInvalid =
    ratingExternalMinValue !== undefined &&
    ratingExternalMaxValue !== undefined &&
    ratingExternalMinValue > ratingExternalMaxValue;

  const pendingFields: FilterFields = {
    search: searchInput.trim() || undefined,
    dateFrom: dateRangeInvalid ? selectedDateFrom : dateFromInput || undefined,
    dateTo: dateRangeInvalid ? selectedDateTo : dateToInput || undefined,
    ratingInternalMin: ratingInternalRangeInvalid ? selectedRatingInternalMin : ratingInternalMinValue,
    ratingInternalMax: ratingInternalRangeInvalid ? selectedRatingInternalMax : ratingInternalMaxValue,
    ratingExternalMin: ratingExternalRangeInvalid ? selectedRatingExternalMin : ratingExternalMinValue,
    ratingExternalMax: ratingExternalRangeInvalid ? selectedRatingExternalMax : ratingExternalMaxValue,
  };
  const committedFields: FilterFields = {
    search: selectedSearch,
    dateFrom: selectedDateFrom,
    dateTo: selectedDateTo,
    ratingInternalMin: selectedRatingInternalMin,
    ratingInternalMax: selectedRatingInternalMax,
    ratingExternalMin: selectedRatingExternalMin,
    ratingExternalMax: selectedRatingExternalMax,
  };

  const pendingQuery = filtersToQuery(pendingFields, selectedGenre, selectedSort);
  const committedQuery = filtersToQuery(committedFields, selectedGenre, selectedSort);
  const pendingKey = JSON.stringify(pendingQuery);
  const committedQueryKey = JSON.stringify(committedQuery);

  // Set by `handleClearFilters` right before it resets the local fields (see
  // its doc comment) so the very next run of the effect below — triggered by
  // that same reset changing `pendingKey` — is skipped instead of scheduling
  // a stale, redundant navigation.
  const skipNextDebounceRef = useRef(false);

  useEffect(() => {
    if (skipNextDebounceRef.current) {
      skipNextDebounceRef.current = false;
      return;
    }
    if (pendingKey === committedQueryKey) return;
    const handle = setTimeout(() => {
      router.replace({ pathname: ADMIN_CATALOG_BASE_PATH[type], query: pendingQuery });
    }, FILTER_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // Only the pending value itself should restart the debounce window —
    // `committedQueryKey`/`pendingQuery`/`type`/`router` are read fresh
    // inside the closure but must not, by themselves, reschedule it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingKey]);

  function navigate(next: { genre?: string; sort: CatalogSort }) {
    router.replace({
      pathname: ADMIN_CATALOG_BASE_PATH[type],
      query: filtersToQuery(pendingFields, next.genre, next.sort),
    });
  }

  function handleClearFilters() {
    skipNextDebounceRef.current = true;
    setSearchInput("");
    setDateFromInput("");
    setDateToInput("");
    setRatingInternalMinInput("");
    setRatingInternalMaxInput("");
    setRatingExternalMinInput("");
    setRatingExternalMaxInput("");
    router.replace({ pathname: ADMIN_CATALOG_BASE_PATH[type], query: {} });
  }

  const genreSelectId = `admin-catalog-genre-${type}`;
  const sortSelectId = `admin-catalog-sort-${type}`;
  const searchId = `admin-catalog-search-${type}`;
  const dateFromId = `admin-catalog-date-from-${type}`;
  const dateToId = `admin-catalog-date-to-${type}`;
  const ratingInternalMinId = `admin-catalog-rating-internal-min-${type}`;
  const ratingInternalMaxId = `admin-catalog-rating-internal-max-${type}`;
  const ratingExternalMinId = `admin-catalog-rating-external-min-${type}`;
  const ratingExternalMaxId = `admin-catalog-rating-external-max-${type}`;

  // Drives the "More filters" trigger's badge — one of these 3 groups counts
  // as active as soon as either side of its range has a value, straight off
  // local input state so it updates as the user types (not after debounce).
  const dateGroupActive = dateFromInput !== "" || dateToInput !== "";
  const ratingInternalGroupActive = ratingInternalMinInput.trim() !== "" || ratingInternalMaxInput.trim() !== "";
  const ratingExternalGroupActive = ratingExternalMinInput.trim() !== "" || ratingExternalMaxInput.trim() !== "";
  const advancedFilterCount = [dateGroupActive, ratingInternalGroupActive, ratingExternalGroupActive].filter(
    Boolean,
  ).length;

  const hasActiveFilters =
    Boolean(selectedGenre) ||
    searchInput.trim() !== "" ||
    dateGroupActive ||
    ratingInternalGroupActive ||
    ratingExternalGroupActive;

  return (
    <div className="flex flex-col gap-3">
      {/*
       * Sort is not a filter — kept in its own row, visually separate from
       * the toolbar below (`border-b`). See the component doc comment's
       * "Third pass" note.
       */}
      <div className="flex flex-wrap items-center gap-4 border-b pb-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={sortSelectId}>{t("sortLabel")}</Label>
          <Select
            value={selectedSort}
            onValueChange={(value) => navigate({ genre: selectedGenre, sort: value as CatalogSort })}
          >
            <SelectTrigger id={sortSelectId} className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATALOG_SORTS.map((sort) => (
                <SelectItem key={sort} value={sort}>
                  {t(`sort.${sort}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/*
       * Compact single-row toolbar (shadcn "Tasks" example / Linear / GitHub
       * pattern — see the doc comment's "Fifth pass" note): every control is
       * `h-9` so heights line up, and only the frequently-used filters
       * (search, genre) live inline — the rest sit behind "More filters".
       */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Label htmlFor={searchId} className="sr-only">
            {t("searchLabel")}
          </Label>
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id={searchId}
            type="search"
            placeholder={t("searchPlaceholder")}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            className="h-9 w-56 pl-8"
          />
        </div>

        <div>
          <Label htmlFor={genreSelectId} className="sr-only">
            {t("genreLabel")}
          </Label>
          <Select
            value={selectedGenre ?? ALL_GENRES_VALUE}
            onValueChange={(value) =>
              navigate({ genre: value === ALL_GENRES_VALUE ? undefined : value, sort: selectedSort })
            }
          >
            <SelectTrigger id={genreSelectId} className="data-[size=default]:h-9 w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_GENRES_VALUE}>{t("genreAll")}</SelectItem>
              {genres.map((genre) => (
                <SelectItem key={genre.slug} value={genre.slug}>
                  {genre.name} ({genre.count})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Popover>
          <PopoverTrigger asChild>
            <Button type="button" variant="outline" size="sm" className="h-9 gap-1.5">
              <SlidersHorizontal className="h-4 w-4" />
              {t("moreFilters")}
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
                    <Label htmlFor={dateFromId}>{t("dateFromLabel")}</Label>
                    <Input
                      id={dateFromId}
                      type="date"
                      className="w-36"
                      value={dateFromInput}
                      onChange={(event) => setDateFromInput(event.target.value)}
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={dateToId}>{t("dateToLabel")}</Label>
                    <Input
                      id={dateToId}
                      type="date"
                      className="w-36"
                      value={dateToInput}
                      onChange={(event) => setDateToInput(event.target.value)}
                    />
                  </div>
                </div>

                {dateRangeInvalid ? (
                  <p role="alert" className="text-xs text-destructive">
                    {t("dateRangeInvalid")}
                  </p>
                ) : null}
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-end gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={ratingInternalMinId}>{t("ratingInternalMinLabel")}</Label>
                    <Input
                      id={ratingInternalMinId}
                      type="number"
                      step="0.1"
                      className="w-24"
                      value={ratingInternalMinInput}
                      onChange={(event) => setRatingInternalMinInput(event.target.value)}
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={ratingInternalMaxId}>{t("ratingInternalMaxLabel")}</Label>
                    <Input
                      id={ratingInternalMaxId}
                      type="number"
                      step="0.1"
                      className="w-24"
                      value={ratingInternalMaxInput}
                      onChange={(event) => setRatingInternalMaxInput(event.target.value)}
                    />
                  </div>
                </div>

                {ratingInternalRangeInvalid ? (
                  <p role="alert" className="text-xs text-destructive">
                    {t("ratingInternalRangeInvalid")}
                  </p>
                ) : null}
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-end gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={ratingExternalMinId}>{t("ratingExternalMinLabel")}</Label>
                    <Input
                      id={ratingExternalMinId}
                      type="number"
                      step="0.1"
                      className="w-24"
                      value={ratingExternalMinInput}
                      onChange={(event) => setRatingExternalMinInput(event.target.value)}
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={ratingExternalMaxId}>{t("ratingExternalMaxLabel")}</Label>
                    <Input
                      id={ratingExternalMaxId}
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
                    {t("ratingExternalRangeInvalid")}
                  </p>
                ) : null}
              </div>
            </div>
          </PopoverContent>
        </Popover>

        {hasActiveFilters ? (
          <Button type="button" variant="ghost" size="sm" onClick={handleClearFilters}>
            {t("clearFilters")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
