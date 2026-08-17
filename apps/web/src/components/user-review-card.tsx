import { Star } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";
import { isCatalogType, type CatalogType } from "@/lib/catalog-types";
import { formatDate } from "@/lib/format-date";
import type { UserReview } from "@/lib/user-content";

const SCORES = [1, 2, 3, 4, 5] as const;

/**
 * Maps the backend's uppercase `UserReviewItemOut.item_type` to the
 * route-segment `CatalogType` used to link to `/{type}/{slug}` (FE-10). Same
 * logic as `toCatalogType` (`@/lib/search.ts`), duplicated rather than
 * imported: that module transitively pulls in `server-only` (via
 * `@/lib/auth/session`), which would break this component's own test suite
 * (and any future Client Component that reuses it) — same rationale
 * `feedItemType` in `@/components/feed-entry-list.tsx` already documents for
 * the identical shape.
 */
function reviewItemType(itemType: string): CatalogType | undefined {
  const lower = itemType.toLowerCase();
  return isCatalogType(lower) ? lower : undefined;
}

/**
 * Extracted from `/u/{username}`'s own `page.tsx` (FE-21) by FE-33, which
 * needs the exact same "one review, one card" rendering on
 * `/admin/users/{username}` (a user's reviews shown alongside their admin
 * detail) — this used to be defined inline (not exported) there, with
 * `ReviewStars` as its own private helper. Kept generic over the translator
 * namespace via `t.dateLabel`'s caller passing `t("reviews.dateLabel", ...)`
 * pre-scoped, rather than requiring a specific `next-intl` namespace here, so
 * both the profile page (`Profile.reviews.dateLabel`) and the future admin
 * detail page (its own `Admin.userDetail.reviews.dateLabel`) can reuse this
 * component without either owning the other's translation namespace.
 *
 * `item-reviews.tsx` has its own, unrelated `ReviewStars` (same visual, tied
 * to that file's own review shape) — not merged with this one, same
 * rationale this component's own extraction doc comment already gives for
 * not duplicating a THIRD copy instead of sharing this one.
 */
export type UserReviewCardProps = {
  review: UserReview;
  locale: string;
  dateLabel: (date: string) => string;
};

export function UserReviewCard({ review, locale, dateLabel }: UserReviewCardProps) {
  const itemType = reviewItemType(review.item.item_type);
  const href = itemType ? `/${itemType}/${review.item.slug}` : undefined;

  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <div className="flex flex-col gap-2">
            {href ? (
              <Link href={href} className="w-fit text-sm font-medium hover:underline">
                {review.item.title}
              </Link>
            ) : (
              <p className="text-sm font-medium">{review.item.title}</p>
            )}
            <ReviewStars score={review.score} />
          </div>
          <p className="text-xs text-muted-foreground">{dateLabel(formatDate(review.created_at, locale))}</p>
        </div>

        {review.review_text ? (
          <p className="max-w-2xl text-sm leading-6 whitespace-pre-wrap text-foreground">
            {review.review_text}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function ReviewStars({ score }: { score: number | null }) {
  return (
    <div className="flex items-center gap-1">
      {SCORES.map((value) => (
        <Star
          key={value}
          aria-hidden
          className={
            score !== null && value <= score
              ? "size-4 fill-current text-yellow-500"
              : "size-4 text-muted-foreground"
          }
        />
      ))}
    </div>
  );
}
