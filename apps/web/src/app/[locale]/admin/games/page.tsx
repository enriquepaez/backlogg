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
 * `/admin/games` (FE-34): fills in the stub FE-33 left in place. Same shape
 * as its `movies`/`series`/`books` siblings, including the second-pass
 * search/date/rating filters (post-QA, feature 50) — see
 * `@/app/[locale]/admin/movies/page.tsx`'s own doc comment.
 */
export default async function AdminGamesPage({
  params,
  searchParams,
}: PageProps<"/[locale]/admin/games">) {
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
    listCatalog("game", {
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
    getGenres("game"),
  ]);

  const totalPages = result.ok ? Math.max(1, Math.ceil(result.total / result.limit)) : 1;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{tSidebar("games")}</h1>
        <p className="text-sm text-muted-foreground">{t("description", { type: tSidebar("games") })}</p>
      </div>

      <AdminCatalogFilters
        type="game"
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
              <AdminCatalogTable type="game" items={result.items} dateLabel={t("dateLabel.game")} />
              <AdminCatalogPagination
                type="game"
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
