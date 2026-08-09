import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { DEFAULT_CATALOG_SORT, type CatalogSort, type CatalogType } from "@/lib/catalog-types";
import { cn } from "@/lib/utils";

export type BrowsePaginationProps = {
  type: CatalogType;
  page: number;
  totalPages: number;
  genre?: string;
  sort: CatalogSort;
};

/**
 * Prev/next pagination for `/browse/{type}` (FE-9). Plain server-rendered
 * `Link`s (like `CatalogSection`'s "view all" link in FE-8) rather than a
 * client component with `router.push` — no interactivity is needed here
 * beyond a normal anchor navigation, and keeping this a Server Component
 * means the links work (and are crawlable/shareable) with JS disabled too.
 */
export async function BrowsePagination({
  type,
  page,
  totalPages,
  genre,
  sort,
}: BrowsePaginationProps) {
  const t = await getTranslations("Browse.pagination");

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
    if (targetPage > 1) {
      query.page = String(targetPage);
    }
    return { pathname: `/browse/${type}`, query };
  }

  const hasPrevious = page > 1;
  const hasNext = page < totalPages;

  return (
    <nav
      aria-label={t("nav")}
      className="flex items-center justify-between gap-4 pt-2"
    >
      {hasPrevious ? (
        <Link
          href={hrefFor(page - 1)}
          className={cn(buttonVariants({ variant: "outline" }))}
        >
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

      <p className="text-sm text-muted-foreground">
        {t("pageStatus", { page, totalPages })}
      </p>

      {hasNext ? (
        <Link
          href={hrefFor(page + 1)}
          className={cn(buttonVariants({ variant: "outline" }))}
        >
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
