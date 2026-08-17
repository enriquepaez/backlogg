import { CATALOG_SORTS, DEFAULT_CATALOG_SORT, type CatalogSort } from "./catalog-types";

/**
 * `searchParams` value parsing for the four `/admin/{movies,series,books,games}`
 * pages (FE-34) — same genre/sort/page vocabulary as `/browse/[type]` (FE-9),
 * duplicated here rather than imported from that page so this feature's
 * files stay self-contained and don't couple to FE-9's own module (which the
 * leader's plan explicitly scoped this feature to NOT touch).
 *
 * Extended (post-QA second pass) with `search`/`date_from`/`date_to`/
 * `rating_internal_min`/`rating_internal_max`/`rating_external_min`/
 * `rating_external_max` — the feature 50 (`catalog_search_filters`) query
 * params `@/lib/catalog.ts`'s `listCatalog` now forwards to
 * `GET /v1/{type}`. Each parser is independently lenient (an absent or
 * malformed value just falls back to `undefined`, same spirit as
 * {@link parseAdminCatalogGenre}) — a malformed value reaching the backend
 * anyway (e.g. a hand-edited URL) still degrades gracefully: `listCatalog`
 * already maps any non-200 response (including the backend's own 422) to
 * `{ ok: false }`, which the four admin pages already render as an inline
 * error state.
 */

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function parseAdminCatalogGenre(value: RawParam): string | undefined {
  const raw = firstValue(value);
  return raw && raw.length > 0 ? raw : undefined;
}

export function parseAdminCatalogSort(value: RawParam): CatalogSort {
  const raw = firstValue(value);
  return raw && (CATALOG_SORTS as readonly string[]).includes(raw)
    ? (raw as CatalogSort)
    : DEFAULT_CATALOG_SORT;
}

export function parseAdminCatalogPage(value: RawParam): number {
  const raw = firstValue(value);
  const parsed = raw ? Number.parseInt(raw, 10) : 1;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

export function parseAdminCatalogSearch(value: RawParam): string | undefined {
  const raw = firstValue(value)?.trim();
  return raw && raw.length > 0 ? raw : undefined;
}

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Accepts only a real `YYYY-MM-DD` calendar date (matches the backend's
 * `date.fromisoformat` — same ISO date shape `<input type="date">` produces),
 * rejecting both malformed strings and shape-valid-but-nonexistent dates
 * (e.g. `2024-02-30`) by round-tripping through `Date.UTC` and comparing the
 * parts back out.
 */
function parseIsoDate(value: RawParam): string | undefined {
  const raw = firstValue(value);
  if (!raw || !ISO_DATE_RE.test(raw)) return undefined;
  const [year, month, day] = raw.split("-").map(Number);
  const asDate = new Date(Date.UTC(year, month - 1, day));
  const roundTrips =
    asDate.getUTCFullYear() === year && asDate.getUTCMonth() === month - 1 && asDate.getUTCDate() === day;
  return roundTrips ? raw : undefined;
}

export function parseAdminCatalogDateFrom(value: RawParam): string | undefined {
  return parseIsoDate(value);
}

export function parseAdminCatalogDateTo(value: RawParam): string | undefined {
  return parseIsoDate(value);
}

function parseRating(value: RawParam): number | undefined {
  const raw = firstValue(value);
  if (!raw) return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function parseAdminCatalogRatingInternalMin(value: RawParam): number | undefined {
  return parseRating(value);
}

export function parseAdminCatalogRatingInternalMax(value: RawParam): number | undefined {
  return parseRating(value);
}

export function parseAdminCatalogRatingExternalMin(value: RawParam): number | undefined {
  return parseRating(value);
}

export function parseAdminCatalogRatingExternalMax(value: RawParam): number | undefined {
  return parseRating(value);
}
