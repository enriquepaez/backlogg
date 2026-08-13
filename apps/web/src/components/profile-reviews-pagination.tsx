import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

export type ProfileReviewsPaginationProps = {
  username: string;
  page: number;
  totalPages: number;
};

/**
 * Prev/next pagination for the reviews section of `/u/{username}` (FE-21),
 * same shape and rationale as `LibraryPagination`: a plain server-rendered
 * `Link`-based nav (works with JS disabled, crawlable) rather than a client
 * component. A dedicated sibling instead of reusing `LibraryPagination`
 * directly — that component's `hrefFor` is hardcoded to
 * `/u/{username}/library` with `status`/`type` query params, none of which
 * apply here (this page has a single `page` query param, targeting
 * `/u/{username}` itself).
 */
export async function ProfileReviewsPagination({
  username,
  page,
  totalPages,
}: ProfileReviewsPaginationProps) {
  const t = await getTranslations("Profile.reviews.pagination");

  if (totalPages <= 1) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const query: Record<string, string> = {};
    if (targetPage > 1) {
      query.page = String(targetPage);
    }
    return { pathname: `/u/${username}`, query };
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
