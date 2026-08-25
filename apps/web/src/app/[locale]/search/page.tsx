import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CatalogCard } from "@/components/catalog-card";
import { RateLimitNotice } from "@/components/rate-limit-notice";
import { SearchControls } from "@/components/search-controls";
import { SearchPagination } from "@/components/search-pagination";
import { isCatalogType, type CatalogType } from "@/lib/catalog-types";
import { searchCatalog, toCatalogType } from "@/lib/search";

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseQuery(value: RawParam): string {
  const raw = firstValue(value);
  return raw ? raw.trim() : "";
}

function parseType(value: RawParam): CatalogType | undefined {
  const raw = firstValue(value);
  return raw && isCatalogType(raw) ? raw : undefined;
}

/**
 * `item.release_date` is a guaranteed `YYYY-MM-DD` ISO string when present
 * (backend `date`, `docs/api.md`) — sliced directly rather than parsed
 * through `Date` to avoid a UTC/local timezone off-by-one on the year for
 * dates near Dec 31/Jan 1.
 */
function releaseYear(releaseDate: string | null): number | null {
  return releaseDate ? Number(releaseDate.slice(0, 4)) : null;
}

function parsePage(value: RawParam): number {
  const raw = firstValue(value);
  const parsed = raw ? Number.parseInt(raw, 10) : 1;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Post-review fix (`progress/review_34.md`): mirrors `parseIsoDate` from
 * `@/lib/admin-catalog-search-params.ts` rather than importing it, following
 * that module's own precedent of staying self-contained instead of coupling
 * to another feature's parsing module. Accepts only a real `YYYY-MM-DD`
 * calendar date (matches the backend's `date.fromisoformat`), rejecting both
 * malformed strings (`"not-a-date"`) and shape-valid-but-nonexistent dates
 * (`"2024-13-45"`, `"2024-02-30"`) by round-tripping through `Date.UTC` and
 * comparing the parts back out — same defensive shape as `parseRatingParam`
 * below (`undefined` on anything invalid, never forwarded to `searchCatalog`).
 */
function parseDateParam(value: RawParam): string | undefined {
  const raw = firstValue(value);
  if (!raw || !ISO_DATE_RE.test(raw)) return undefined;
  const [year, month, day] = raw.split("-").map(Number);
  const asDate = new Date(Date.UTC(year, month - 1, day));
  const roundTrips =
    asDate.getUTCFullYear() === year && asDate.getUTCMonth() === month - 1 && asDate.getUTCDate() === day;
  return roundTrips ? raw : undefined;
}

/** Parses `rating_external_min`/`rating_external_max` — `undefined` on anything that isn't a finite number, same defensive shape as `parsePage`. */
function parseRatingParam(value: RawParam): number | undefined {
  const raw = firstValue(value);
  if (!raw) return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

/**
 * Static OG metadata for `/search` (FE-11) — unlike `/browse/{type}`'s
 * `generateMetadata` (FE-9), there is no single "the query" to interpolate:
 * `q` is free text supplied by the visitor, not a fixed content dimension
 * worth indexing per-value, so this is a single generic title/description
 * regardless of `searchParams`.
 */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/search">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.search" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

export default async function SearchPage({
  params,
  searchParams,
}: PageProps<"/[locale]/search">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const q = parseQuery(query.q);
  const type = parseType(query.type);
  const page = parsePage(query.page);
  const dateFrom = parseDateParam(query.date_from);
  const dateTo = parseDateParam(query.date_to);
  const ratingExternalMin = parseRatingParam(query.rating_external_min);
  const ratingExternalMax = parseRatingParam(query.rating_external_max);

  const [t, tType] = await Promise.all([
    getTranslations("Search"),
    getTranslations("Browse"),
  ]);

  // Re-scope of FE-35 (`browse_search_filters`, Fase 1 backend): `GET
  // /v1/search` now accepts a filters-only search (no `q`), so the "empty
  // prompt" state (FE-11 acceptance: "estado vacío") is reserved for when
  // NEITHER `q` NOR any of the four advanced filters are active — a fetch
  // fires as soon as any one of them is. The 422 the backend can still
  // return (an explicit empty `q`, or an inverted range) is only reachable
  // defensively, through a malformed/hand-edited URL (see the
  // `status === "invalid"` branch below), not through normal use of
  // `SearchControls`.
  const hasActiveFilters =
    dateFrom !== undefined ||
    dateTo !== undefined ||
    ratingExternalMin !== undefined ||
    ratingExternalMax !== undefined;
  const result =
    q || hasActiveFilters
      ? await searchCatalog(q, { type, page, dateFrom, dateTo, ratingExternalMin, ratingExternalMax })
      : null;

  const totalPages =
    result && result.status === "ok" ? Math.max(1, Math.ceil(result.total / result.limit)) : 1;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("heading")}</h1>

      <SearchControls
        initialQuery={q}
        initialType={type}
        initialDateFrom={dateFrom}
        initialDateTo={dateTo}
        initialRatingExternalMin={ratingExternalMin}
        initialRatingExternalMax={ratingExternalMax}
      />

      {!result ? (
        <p className="text-sm text-muted-foreground">{t("prompt")}</p>
      ) : result.status === "invalid" ? (
        <p role="alert" className="text-sm text-destructive">
          {t("invalidQuery")}
        </p>
      ) : result.status === "rate-limited" ? (
        <RateLimitNotice retryAfterSeconds={result.retryAfterSeconds} />
      ) : result.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty", { query: q })}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {result.results.map((item) => {
              const itemType = toCatalogType(item.item_type);
              return (
                <CatalogCard
                  key={`${item.item_type}-${item.slug}`}
                  title={item.title ?? t("untitled")}
                  year={releaseYear(item.release_date)}
                  posterUrl={item.poster_url}
                  ratingInternal={item.rating_internal}
                  typeLabel={itemType ? tType(`heading.${itemType}`) : item.item_type}
                  href={itemType ? `/${itemType}/${item.slug}` : undefined}
                />
              );
            })}
          </div>

          <SearchPagination
            query={q}
            type={type}
            page={result.page}
            totalPages={totalPages}
            dateFrom={dateFrom}
            dateTo={dateTo}
            ratingExternalMin={ratingExternalMin}
            ratingExternalMax={ratingExternalMax}
          />
        </>
      )}
    </div>
  );
}
