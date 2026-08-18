import { CheckCircle2, Heart, ImageOff, Star } from "lucide-react";
import Image from "next/image";
import { getTranslations } from "next-intl/server";

import { Card, CardContent } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";
import { isCatalogType, type CatalogType } from "@/lib/catalog-types";
import { formatDate } from "@/lib/format-date";
import { STATUS_COLOR_CLASSES } from "@/lib/library-types";
import { cn } from "@/lib/utils";

import type { components } from "@backlogg/api-client";

export type FeedEntry = components["schemas"]["FeedEntryOut"];

const SCORES = [1, 2, 3, 4, 5] as const;

/**
 * Maps the backend's uppercase `FeedItemOut.item_type` to the route-segment
 * `CatalogType` used to link to `/{type}/{slug}` (FE-10). Same logic as
 * `toCatalogType` (`@/lib/search.ts`), duplicated rather than imported: that
 * module transitively pulls in `server-only` (via `@/lib/auth/session`),
 * which would make this component's own test suite require the
 * `@vitest-environment node` override the rest of this file has no other
 * reason to need — same "small, self-contained helper beats an awkward
 * cross-module dependency" rationale `trendingItemType` (`[locale]/page.tsx`)
 * already applies for the same underlying shape.
 */
function feedItemType(itemType: string): CatalogType | undefined {
  const lower = itemType.toLowerCase();
  return isCatalogType(lower) ? lower : undefined;
}

export type FeedEntryListProps = {
  entries: FeedEntry[];
  locale: string;
};

/**
 * List of feed entries (FE-23, `/feed`; `status_completed` support added by
 * FE-42): each one shows its author (avatar+name, linked to `/u/{username}`)
 * and item (poster+title, linked to `/{type}/{slug}`). What else it shows
 * depends on `entry.event_type` (see `FeedEntryCard`):
 *
 * - `rating_created`: score (stars), review text and like count.
 * - `status_completed`: a "completed" badge (`STATUS_COLOR_CLASSES.completed`,
 *   same status color as FE-37's library UI) instead — the backend always
 *   sends `score`/`review_text`/`like_count` as `null` for this type
 *   (`docs/api.md`), so those three pieces of UI are already absent without
 *   any extra branching; only the badge needs one.
 *
 * Deliberately non-interactive — unlike `ItemReviews`'s `ReviewCard`, FE-23's
 * acceptance only calls for *rendering* `like_count`, not toggling it from
 * the feed; liking a review still happens on that review's own item detail
 * page.
 */
export async function FeedEntryList({ entries, locale }: FeedEntryListProps) {
  const t = await getTranslations("Feed.entry");

  return (
    <div className="flex flex-col gap-4">
      {entries.map((entry) => (
        <FeedEntryCard key={entry.id} entry={entry} locale={locale} t={t} />
      ))}
    </div>
  );
}

type FeedEntryTranslator = Awaited<ReturnType<typeof getTranslations<"Feed.entry">>>;

function FeedEntryCard({
  entry,
  locale,
  t,
}: {
  entry: FeedEntry;
  locale: string;
  t: FeedEntryTranslator;
}) {
  const itemType = feedItemType(entry.item.item_type);
  const itemHref = itemType ? `/${itemType}/${entry.item.slug}` : undefined;
  const isCompleted = entry.event_type === "status_completed";

  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <FeedEntryAuthor author={entry.author} />
          <p className="text-xs text-muted-foreground">
            {isCompleted
              ? t("completedDateLabel", { date: formatDate(entry.created_at, locale) })
              : t("dateLabel", { date: formatDate(entry.created_at, locale) })}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative h-16 w-11 shrink-0 overflow-hidden rounded-md bg-muted">
            {entry.item.poster_url ? (
              <Image
                src={entry.item.poster_url}
                alt=""
                fill
                sizes="44px"
                className="object-cover"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-muted-foreground">
                <ImageOff aria-hidden className="size-4" />
              </div>
            )}
          </div>
          <div className="flex flex-col gap-1">
            {itemHref ? (
              <Link href={itemHref} className="w-fit text-sm font-medium hover:underline">
                {entry.item.title}
              </Link>
            ) : (
              <p className="text-sm font-medium">{entry.item.title}</p>
            )}
            {isCompleted ? <FeedEntryCompletedBadge t={t} /> : <FeedEntryStars score={entry.score} />}
          </div>
        </div>

        {entry.review_text ? (
          <p className="max-w-2xl text-sm leading-6 whitespace-pre-wrap text-foreground">
            {entry.review_text}
          </p>
        ) : null}

        {entry.like_count !== null ? (
          <div className="flex w-fit items-center gap-1.5 text-sm text-muted-foreground">
            <Heart aria-hidden className="size-4" />
            {t("likeCount", { count: entry.like_count })}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * Avatar + name of a feed entry's author, linked to their public profile
 * (`/u/{username}`, FE-21) — same shape as `ReviewAuthor`
 * (`item-reviews.tsx`) and `FollowUserList`'s row, duplicated rather than
 * shared per this codebase's established "different call sites, a few
 * duplicated lines beat a forced shared abstraction" rationale (see
 * `ReviewAuthor`'s own doc comment).
 */
function FeedEntryAuthor({ author }: { author: FeedEntry["author"] }) {
  const name = author.display_name ?? author.username;

  return (
    <Link href={`/u/${author.username}`} className="flex w-fit items-center gap-2">
      {author.avatar_url ? (
        // Avatar hosts aren't configured in next/image's remotePatterns yet
        // (catalog-image scope, later features) — same rationale as
        // `ReviewAuthor` in `item-reviews.tsx`.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={author.avatar_url} alt="" className="size-6 rounded-full object-cover" />
      ) : (
        <span
          aria-hidden="true"
          className="flex size-6 items-center justify-center rounded-full bg-muted text-xs"
        >
          {name.slice(0, 2).toUpperCase()}
        </span>
      )}
      <span className="text-sm font-medium hover:underline">{name}</span>
    </Link>
  );
}

/**
 * Status pill shown on a `status_completed` entry in place of
 * `FeedEntryStars` (there is no score for this event type) — same
 * `STATUS_COLOR_CLASSES.completed` color and pill shape `CatalogCard` uses
 * for the viewer's own library-status badge (FE-37), for visual consistency
 * between "you marked this completed" (library) and "someone you follow
 * marked this completed" (feed) even though the two badges live in
 * different components with different data. `CheckCircle2` (not reused from
 * anywhere else in the codebase — no prior "completed" icon convention
 * existed before this feature) reads as "done" at a glance next to the
 * item's title, mirroring the "X completed Y" shape asked for by pairing
 * this badge with the author name already shown above and the item title
 * already shown to its left.
 */
function FeedEntryCompletedBadge({ t }: { t: FeedEntryTranslator }) {
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold",
        STATUS_COLOR_CLASSES.completed,
      )}
    >
      <CheckCircle2 aria-hidden className="size-3.5" />
      {t("completedBadge")}
    </span>
  );
}

function FeedEntryStars({ score }: { score: number | null }) {
  if (score === null) {
    return null;
  }

  return (
    <div className="flex items-center gap-1">
      {SCORES.map((value) => (
        <Star
          key={value}
          aria-hidden
          className={
            value <= score ? "size-4 fill-current text-yellow-500" : "size-4 text-muted-foreground"
          }
        />
      ))}
    </div>
  );
}
