import { getTranslations, setRequestLocale } from "next-intl/server";

import { AdminCatalogFilters } from "@/components/admin-catalog-filters";
import { AdminCatalogPagination } from "@/components/admin-catalog-pagination";
import { AdminCatalogTable } from "@/components/admin-catalog-table";
import { getGenres, listCatalog } from "@/lib/catalog";
import {
  parseAdminCatalogDateFrom,
  parseAdminCatalogDateTo,
  parseAdminCatalogGenre,
  parseAdminCatalogPage,
  parseAdminCatalogRatingExternalMax,
  parseAdminCatalogRatingExternalMin,
  parseAdminCatalogRatingInternalMax,
  parseAdminCatalogRatingInternalMin,
  parseAdminCatalogSearch,
  parseAdminCatalogSort,
} from "@/lib/admin-catalog-search-params";

/**
 * `/admin/movies` (FE-34): fills in the stub FE-33 left in place
 * (`AdminComingSoon`, now unused and removed by this feature). Paginated,
 * filterable movie listing sourced from `listCatalog`/`getGenres`
 * (`@/lib/catalog.ts`) — the same public, no-auth data `/browse/[type]`
 * (FE-9) uses, since `GET /v1/movies` needs no `X-API-Key` to list. Filters
 * and pagination are URL-synced Server Components exactly like FE-9's own
 * `BrowseFilters`/`BrowsePagination` (not reused directly — this is
 * admin-only markup matching the `/admin/users` visual pattern this feature
 * was asked to follow: a real `<table>`, `Select`s with a visible `Label`, a
 * "showing N of total" indicator), via `AdminCatalogFilters`/
 * `AdminCatalogPagination`.
 *
 * `AdminCatalogTable` renders the table itself plus the "Edit" action per
 * row, which opens `AdminCatalogEditDialog` — the manual-edit form backed by
 * feature 49's `PATCH /v1/admin/movie/{slug}` (proxied by
 * `/api/admin/[type]/[slug]`).
 *
 * Extended in a second pass (post-QA of the first version: "filtros
 * insuficientes, además debe dejar buscar por nombre, fecha, rating") to
 * also parse and forward `search`/`date_from`/`date_to`/
 * `rating_internal_min`/`rating_internal_max`/`rating_external_min`/
 * `rating_external_max` — feature 50 (`catalog_search_filters`) added these
 * to `GET /v1/{type}` after this page's first version shipped, when they
 * weren't available yet.
 *
 * The auth+`is_admin` gate lives in `@/app/[locale]/admin/layout.tsx`, which
 * wraps this route — nothing to check here.
 */
export default async function AdminMoviesPage({
  params,
  searchParams,
}: PageProps<"/[locale]/admin/movies">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const genre = parseAdminCatalogGenre(query.genre);
  const sort = parseAdminCatalogSort(query.sort);
  const page = parseAdminCatalogPage(query.page);
  const search = parseAdminCatalogSearch(query.search);
  const dateFrom = parseAdminCatalogDateFrom(query.date_from);
  const dateTo = parseAdminCatalogDateTo(query.date_to);
  const ratingInternalMin = parseAdminCatalogRatingInternalMin(query.rating_internal_min);
  const ratingInternalMax = parseAdminCatalogRatingInternalMax(query.rating_internal_max);
  const ratingExternalMin = parseAdminCatalogRatingExternalMin(query.rating_external_min);
  const ratingExternalMax = parseAdminCatalogRatingExternalMax(query.rating_external_max);

  const [t, tSidebar, result, genres] = await Promise.all([
    getTranslations({ locale, namespace: "Admin.catalog" }),
    getTranslations({ locale, namespace: "Admin.sidebar" }),
    listCatalog("movie", {
      genre,
      sort,
      page,
      search,
      dateFrom,
      dateTo,
      ratingInternalMin,
      ratingInternalMax,
      ratingExternalMin,
      ratingExternalMax,
    }),
    getGenres("movie"),
  ]);

  const totalPages = result.ok ? Math.max(1, Math.ceil(result.total / result.limit)) : 1;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{tSidebar("movies")}</h1>
        <p className="text-sm text-muted-foreground">{t("description", { type: tSidebar("movies") })}</p>
      </div>

      <AdminCatalogFilters
        type="movie"
        genres={genres}
        selectedGenre={genre}
        selectedSort={sort}
        selectedSearch={search}
        selectedDateFrom={dateFrom}
        selectedDateTo={dateTo}
        selectedRatingInternalMin={ratingInternalMin}
        selectedRatingInternalMax={ratingInternalMax}
        selectedRatingExternalMin={ratingExternalMin}
        selectedRatingExternalMax={ratingExternalMax}
      />

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {t("resultsCount", { shown: result.items.length, total: result.total })}
          </p>
          {result.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("empty")}</p>
          ) : (
            <>
              <AdminCatalogTable type="movie" items={result.items} dateLabel={t("dateLabel.movie")} />
              <AdminCatalogPagination
                type="movie"
                page={result.page}
                totalPages={totalPages}
                genre={genre}
                sort={sort}
                search={search}
                dateFrom={dateFrom}
                dateTo={dateTo}
                ratingInternalMin={ratingInternalMin}
                ratingInternalMax={ratingInternalMax}
                ratingExternalMin={ratingExternalMin}
                ratingExternalMax={ratingExternalMax}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
