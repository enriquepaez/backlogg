import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import { cn } from "@/lib/utils";

export type SearchPaginationProps = {
  query: string;
  type?: CatalogType;
  page: number;
  totalPages: number;
};

/**
 * Prev/next pagination for `/search` (FE-11), same shape and rationale as
 * `BrowsePagination` (FE-9) — a plain server-rendered `Link`-based nav
 * (works with JS disabled, crawlable) rather than a client component. Kept
 * as its own component instead of generalizing `BrowsePagination` itself:
 * that one is coupled to `/browse/{type}` plus `genre`/`sort`, while this
 * one is coupled to the fixed `/search` route plus `q`/`type` — different
 * enough query shapes that sharing one component would need a bigger,
 * riskier refactor than FE-11's scope calls for.
 */
export async function SearchPagination({ query, type, page, totalPages }: SearchPaginationProps) {
  const t = await getTranslations("Search.pagination");

  if (totalPages <= 1) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const q: Record<string, string> = { q: query };
    if (type) {
      q.type = type;
    }
    if (targetPage > 1) {
      q.page = String(targetPage);
    }
    return { pathname: "/search", query: q };
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
