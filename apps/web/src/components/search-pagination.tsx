import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { SearchPaginationStatus } from "@/components/search-pagination-status";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import { cn } from "@/lib/utils";

export type SearchPaginationProps = {
  query: string;
  type?: CatalogType;
  page: number;
  totalPages: number;
  /**
   * Re-scope of FE-35 (`browse_search_filters`): the date-range and
   * external-rating-range filters currently active, preserved in the
   * previous/next page links the same way `type` already is.
   */
  dateFrom?: string;
  dateTo?: string;
  ratingExternalMin?: number;
  ratingExternalMax?: number;
};

/**
 * Prev/next pagination for `/search` (FE-11), same shape and rationale as
 * `BrowsePagination` (FE-9) — a plain server-rendered `Link`-based nav
 * (works with JS disabled, crawlable) rather than a client component. Kept
 * as its own component instead of generalizing `BrowsePagination` itself:
 * that one is coupled to `/browse/{type}` plus `genre`/`sort`, while this
 * one is coupled to the fixed `/search` route plus `q`/`type`/the four
 * advanced filters (re-scope of FE-35) — different enough query shapes that
 * sharing one component would need a bigger, riskier refactor than FE-11's
 * scope calls for.
 */
export async function SearchPagination({
  query,
  type,
  page,
  totalPages,
  dateFrom,
  dateTo,
  ratingExternalMin,
  ratingExternalMax,
}: SearchPaginationProps) {
  const t = await getTranslations("Search.pagination");

  if (totalPages <= 1) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const q: Record<string, string> = {};
    if (query) {
      q.q = query;
    }
    if (type) {
      q.type = type;
    }
    if (dateFrom) {
      q.date_from = dateFrom;
    }
    if (dateTo) {
      q.date_to = dateTo;
    }
    if (ratingExternalMin !== undefined) {
      q.rating_external_min = String(ratingExternalMin);
    }
    if (ratingExternalMax !== undefined) {
      q.rating_external_max = String(ratingExternalMax);
    }
    if (targetPage > 1) {
      q.page = String(targetPage);
    }
    return { pathname: "/search", query: q };
  }

  const hasPrevious = page > 1;
  const hasNext = page < totalPages;

  return (
    <nav
      aria-label={t("nav")}
      className="relative flex items-center justify-between gap-4 pt-2"
    >
      {hasPrevious ? (
        <Link href={hrefFor(page - 1)} className={cn(buttonVariants({ variant: "outline" }))}>
          {t("previous")}
          <SearchPaginationStatus label={t("loadingMore")} />
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
          <SearchPaginationStatus label={t("loadingMore")} />
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
