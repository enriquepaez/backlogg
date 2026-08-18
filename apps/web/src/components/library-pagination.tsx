import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import type { LibraryStatusValue } from "@/lib/library";
import { DEFAULT_LIBRARY_SORT, type LibrarySort } from "@/lib/library-types";
import { cn } from "@/lib/utils";

export type LibraryPaginationProps = {
  username: string;
  status?: LibraryStatusValue;
  type?: CatalogType;
  sort?: LibrarySort;
  page: number;
  totalPages: number;
};

/**
 * Prev/next pagination for `/u/{username}/library` (FE-20; `sort` added in
 * FE-38), same shape and rationale as `BrowsePagination`/`SearchPagination`:
 * a plain server-rendered `Link`-based nav (works with JS disabled,
 * crawlable) rather than a client component. Its own sibling instead of
 * generalizing either of those — `search-pagination.tsx`'s own doc comment
 * already explains why that refactor isn't worth it for a third,
 * differently-shaped query (`status`/`type`/`sort` here vs `genre`/`sort`
 * or `q`/`type`).
 */
export async function LibraryPagination({
  username,
  status,
  type,
  sort,
  page,
  totalPages,
}: LibraryPaginationProps) {
  const t = await getTranslations("Library.pagination");

  if (totalPages <= 1) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const query: Record<string, string> = {};
    if (status) {
      query.status = status;
    }
    if (type) {
      query.type = type;
    }
    if (sort && sort !== DEFAULT_LIBRARY_SORT) {
      query.sort = sort;
    }
    if (targetPage > 1) {
      query.page = String(targetPage);
    }
    return { pathname: `/u/${username}/library`, query };
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
