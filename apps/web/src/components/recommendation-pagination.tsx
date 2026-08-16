import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import { cn } from "@/lib/utils";

export type RecommendationsPaginationProps = {
  type?: CatalogType;
  page: number;
  /**
   * Whether the current page came back full (`results.length === limit`,
   * decided by the caller — see `getRecommendations`'s doc comment). Stands
   * in for `totalPages` (used by `FeedPagination`/`BrowsePagination`):
   * `RecommendationsOut` never returns a `total` count, since recommendations
   * are computed on the fly rather than counted ahead of time
   * (`docs/api.md`), so there is no page count to compare against — only
   * "does a next page exist".
   */
  hasNext: boolean;
};

/**
 * Prev/next pagination for `/recommendations` (FE-27), same plain
 * server-rendered `Link` shape as `FeedPagination`/`BrowsePagination` (works
 * with JS disabled, crawlable). Unlike those, there is no `totalPages` to
 * center a page-count label on (see {@link RecommendationsPaginationProps}),
 * so this only renders prev/next controls, no "Page X of Y" text.
 */
export async function RecommendationsPagination({
  type,
  page,
  hasNext,
}: RecommendationsPaginationProps) {
  const t = await getTranslations("Recommendations.pagination");

  if (page <= 1 && !hasNext) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const query: Record<string, string> = {};
    if (type) {
      query.type = type;
    }
    if (targetPage > 1) {
      query.page = String(targetPage);
    }
    return { pathname: "/recommendations", query };
  }

  const hasPrevious = page > 1;

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

      <p className="text-sm text-muted-foreground">{t("pageStatus", { page })}</p>

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
