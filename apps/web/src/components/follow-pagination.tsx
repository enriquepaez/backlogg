import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

export type FollowPaginationProps = {
  /** Base path this pagination targets — `/u/{username}/followers` or `/u/{username}/following` (FE-23). */
  href: string;
  page: number;
  totalPages: number;
};

/**
 * Prev/next pagination shared by `/u/{username}/followers` and
 * `/u/{username}/following` (FE-23), same shape and rationale as
 * `ProfileReviewsPagination`: a plain server-rendered `Link`-based nav
 * (works with JS disabled, crawlable). Parametrized by `href` — unlike
 * `LibraryPagination` vs `ProfileReviewsPagination` (split because those two
 * have genuinely different query-param shapes), followers and following
 * share the exact same single-`page`-param shape, only the base path
 * differs, so one component serves both instead of two near-duplicates.
 */
export async function FollowPagination({ href, page, totalPages }: FollowPaginationProps) {
  const t = await getTranslations("Follows.pagination");

  if (totalPages <= 1) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const query: Record<string, string> = {};
    if (targetPage > 1) {
      query.page = String(targetPage);
    }
    return { pathname: href, query };
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
