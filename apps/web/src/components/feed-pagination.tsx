import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import type { FeedTab } from "@/lib/feed-types";
import { cn } from "@/lib/utils";

export type FeedPaginationProps = {
  tab: FeedTab;
  page: number;
  totalPages: number;
};

/**
 * Prev/next pagination for `/feed` (FE-23), same shape and rationale as
 * `FollowPagination`/`ProfileReviewsPagination`: a plain server-rendered
 * `Link`-based nav (works with JS disabled, crawlable). A dedicated sibling
 * rather than reusing either of those directly — this page's query shape
 * (`tab` + `page`, both against the single `/feed` path) matches neither
 * `FollowPagination`'s `href`-parametrized single-`page` shape nor
 * `ProfileReviewsPagination`'s hardcoded `/u/{username}` path closely enough
 * to be worth forcing.
 */
export async function FeedPagination({ tab, page, totalPages }: FeedPaginationProps) {
  const t = await getTranslations("Feed.pagination");

  if (totalPages <= 1) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const query: Record<string, string> = {};
    if (tab !== "following") {
      query.tab = tab;
    }
    if (targetPage > 1) {
      query.page = String(targetPage);
    }
    return { pathname: "/feed", query };
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
