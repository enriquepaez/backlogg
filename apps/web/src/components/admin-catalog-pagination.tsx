import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { ADMIN_CATALOG_BASE_PATH } from "@/lib/admin-catalog";
import { DEFAULT_CATALOG_SORT, type CatalogSort, type CatalogType } from "@/lib/catalog-types";
import { cn } from "@/lib/utils";

export type AdminCatalogPaginationProps = {
  type: CatalogType;
  page: number;
  totalPages: number;
  genre?: string;
  sort: CatalogSort;
  /** Feature 50 params (`docs/api.md`), preserved across page links since FE-34's post-QA second pass. */
  search?: string;
  dateFrom?: string;
  dateTo?: string;
  ratingInternalMin?: number;
  ratingInternalMax?: number;
  ratingExternalMin?: number;
  ratingExternalMax?: number;
};

/**
 * Prev/next pagination for `/admin/{movies,series,books,games}` (FE-34) —
 * same structure as `/browse/[type]`'s `BrowsePagination` (FE-9): a plain
 * server-rendered `Link` pair (works with JS disabled), not reused directly
 * since it targets `/browse/{type}`, not this feature's `/admin/*` routes.
 *
 * Extended (post-QA second pass) to also preserve the feature 50 search/date/
 * rating filters in every page link, same as `genre`/`sort` already did —
 * otherwise clicking "next"/"previous" would silently drop those filters.
 */
export async function AdminCatalogPagination({
  type,
  page,
  totalPages,
  genre,
  sort,
  search,
  dateFrom,
  dateTo,
  ratingInternalMin,
  ratingInternalMax,
  ratingExternalMin,
  ratingExternalMax,
}: AdminCatalogPaginationProps) {
  const t = await getTranslations("Admin.catalog.pagination");

  if (totalPages <= 1) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const query: Record<string, string> = {};
    if (genre) {
      query.genre = genre;
    }
    if (sort !== DEFAULT_CATALOG_SORT) {
      query.sort = sort;
    }
    if (search) {
      query.search = search;
    }
    if (dateFrom) {
      query.date_from = dateFrom;
    }
    if (dateTo) {
      query.date_to = dateTo;
    }
    if (ratingInternalMin !== undefined) {
      query.rating_internal_min = String(ratingInternalMin);
    }
    if (ratingInternalMax !== undefined) {
      query.rating_internal_max = String(ratingInternalMax);
    }
    if (ratingExternalMin !== undefined) {
      query.rating_external_min = String(ratingExternalMin);
    }
    if (ratingExternalMax !== undefined) {
      query.rating_external_max = String(ratingExternalMax);
    }
    if (targetPage > 1) {
      query.page = String(targetPage);
    }
    return { pathname: ADMIN_CATALOG_BASE_PATH[type], query };
  }

  const hasPrevious = page > 1;
  const hasNext = page < totalPages;

  return (
    <nav aria-label={t("nav")} className="flex items-center justify-between gap-4 pt-2">
      {hasPrevious ? (
        <Link href={hrefFor(page - 1)} className={cn(buttonVariants({ variant: "outline" }))}>
          {t("previous")}
        </Link>
      ) : (
        <span
          aria-disabled="true"
          className={cn(buttonVariants({ variant: "outline" }), "pointer-events-none opacity-50")}
        >
          {t("previous")}
        </span>
      )}

      <p className="text-sm text-muted-foreground">{t("pageStatus", { page, totalPages })}</p>

      {hasNext ? (
        <Link href={hrefFor(page + 1)} className={cn(buttonVariants({ variant: "outline" }))}>
          {t("next")}
        </Link>
      ) : (
        <span
          aria-disabled="true"
          className={cn(buttonVariants({ variant: "outline" }), "pointer-events-none opacity-50")}
        >
          {t("next")}
        </span>
      )}
    </nav>
  );
}
