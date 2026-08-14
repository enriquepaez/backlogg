import { Star } from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { CatalogCard } from "@/components/catalog-card";
import { FollowWidget } from "@/components/follow-widget";
import { ProfileReviewsPagination } from "@/components/profile-reviews-pagination";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";
import { getCurrentUser } from "@/lib/api-fetch";
import { formatDate } from "@/lib/format-date";
import { getUserLibrary, getUserProfile, LIBRARY_STATUSES, type LibraryEntry, type UserProfile } from "@/lib/library";
import { toCatalogType } from "@/lib/search";
import { getUserLists, getUserReviews, type UserListSummary, type UserReview } from "@/lib/user-content";
import { cn } from "@/lib/utils";

/** Page size for the reviews section — matches `PAGE_LIMIT` in `item-reviews.tsx`. */
const REVIEWS_PAGE_SIZE = 10;

/**
 * Item count for the library preview grid on this page — a taste, not the
 * full listing that `/u/{username}/library` (FE-20) already owns. Six items
 * fill exactly one row of the `lg:grid-cols-6` layout below.
 */
const LIBRARY_PREVIEW_SIZE = 6;

const SCORES = [1, 2, 3, 4, 5] as const;

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parsePage(value: RawParam): number {
  const raw = firstValue(value);
  const parsed = raw ? Number.parseInt(raw, 10) : 1;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

type ProfileTranslator = Awaited<ReturnType<typeof getTranslations<"Profile">>>;
type LibraryStatusTranslator = Awaited<ReturnType<typeof getTranslations<"Library.statusTabs">>>;
type BrowseTranslator = Awaited<ReturnType<typeof getTranslations<"Browse">>>;

/**
 * Public profile page for one user (FE-21), `/u/{username}` — the full
 * profile that `/u/{username}/library` (FE-20) and `item-reviews.tsx`'s
 * author link both already reference. Loads the profile (`getUserProfile`),
 * this page's own reviews (`getUserReviews`, paginated via the `page` query
 * param), public lists (`getUserLists`) and a small library preview
 * (`getUserLibrary`, capped at `LIBRARY_PREVIEW_SIZE`) in parallel, plus the
 * caller's own session (`getCurrentUser`) to tell own vs. someone else's
 * profile apart.
 *
 * Only a backend-confirmed 404 username goes through `notFound()` — same
 * `not-found`/`error` split as `getItemDetail`'s doc comment
 * (`src/lib/catalog.ts`) and the sibling library page. Reviews/lists/library
 * failures degrade to their own inline error states (or, for the library
 * preview, silently fall back to the counts-only summary) instead of failing
 * the whole page, since the profile header itself is still valid and worth
 * showing.
 */
export default async function UserProfilePage({
  params,
  searchParams,
}: PageProps<"/[locale]/u/[username]">) {
  const { locale, username } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const page = parsePage(query.page);

  const [t, tLibraryStatus, tType, profileResult, reviewsResult, listsResult, libraryResult, currentUser] =
    await Promise.all([
      getTranslations("Profile"),
      getTranslations("Library.statusTabs"),
      getTranslations("Browse"),
      getUserProfile(username),
      getUserReviews(username, { page, limit: REVIEWS_PAGE_SIZE }),
      getUserLists(username),
      getUserLibrary(username, { limit: LIBRARY_PREVIEW_SIZE }),
      getCurrentUser(),
    ]);

  if (profileResult.status === "not-found") {
    notFound();
  }

  if (profileResult.status === "error") {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-16">
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      </div>
    );
  }

  const profile = profileResult.profile;
  const isOwnProfile = currentUser?.username === username;
  const totalReviewPages = reviewsResult.ok
    ? Math.max(1, Math.ceil(reviewsResult.total / reviewsResult.limit))
    : 1;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-10 px-6 py-16">
      <ProfileHeader profile={profile} isOwnProfile={isOwnProfile} t={t} />

      <LibrarySummary
        username={username}
        counts={profile.library_counts}
        preview={libraryResult.ok ? libraryResult.items : []}
        t={t}
        tStatus={tLibraryStatus}
        tType={tType}
      />

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-medium">{t("reviews.heading")}</h2>
        {!reviewsResult.ok ? (
          <p role="alert" className="text-sm text-destructive">
            {t("reviews.error")}
          </p>
        ) : reviewsResult.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("reviews.empty")}</p>
        ) : (
          <>
            <div className="flex flex-col gap-4">
              {reviewsResult.items.map((review) => (
                <ProfileReviewCard key={review.id} review={review} locale={locale} t={t} />
              ))}
            </div>
            <ProfileReviewsPagination username={username} page={page} totalPages={totalReviewPages} />
          </>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-medium">{t("lists.heading")}</h2>
        {!listsResult.ok ? (
          <p role="alert" className="text-sm text-destructive">
            {t("lists.error")}
          </p>
        ) : listsResult.lists.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("lists.empty")}</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {listsResult.lists.map((list) => (
              <ProfileListCard key={list.slug} list={list} t={t} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ProfileHeader({
  profile,
  isOwnProfile,
  t,
}: {
  profile: UserProfile;
  isOwnProfile: boolean;
  t: ProfileTranslator;
}) {
  const name = profile.display_name ?? profile.username;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          {profile.avatar_url ? (
            // Avatar hosts aren't configured in next/image's remotePatterns yet
            // (catalog-image scope, later features) — same rationale as
            // `ReviewAuthor` in `item-reviews.tsx`.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={profile.avatar_url}
              alt=""
              className="size-16 rounded-full object-cover"
            />
          ) : (
            <span
              aria-hidden="true"
              className="flex size-16 items-center justify-center rounded-full bg-muted text-lg font-medium"
            >
              {name.slice(0, 2).toUpperCase()}
            </span>
          )}
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold tracking-tight">{name}</h1>
            <p className="text-sm text-muted-foreground">@{profile.username}</p>
          </div>
        </div>

        {isOwnProfile ? (
          <Link href="/settings" className={cn(buttonVariants({ variant: "outline" }))}>
            {t("editProfileLink")}
          </Link>
        ) : null}
      </div>

      {profile.bio ? <p className="max-w-2xl text-sm leading-6 text-foreground">{profile.bio}</p> : null}

      <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
        <FollowWidget
          username={profile.username}
          initialFollowerCount={profile.follower_count}
          isOwnProfile={isOwnProfile}
        />
        <Link href={`/u/${profile.username}/following`} className="hover:text-foreground hover:underline">
          {t("followingCount", { count: profile.following_count })}
        </Link>
      </div>
    </div>
  );
}

/**
 * Library section of the profile (FE-21, enriched post-QA): the per-status
 * counts remain the at-a-glance summary, now paired with a small poster
 * preview (`CatalogCard`, same component the full library grid at
 * `/u/{username}/library` uses) of the user's `LIBRARY_PREVIEW_SIZE` most
 * recent entries — plain counts alone read as too sparse. The preview is
 * simply omitted when `preview` is empty (no empty-state copy), same as how
 * the full library page treats a genuinely empty library.
 */
function LibrarySummary({
  username,
  counts,
  preview,
  t,
  tStatus,
  tType,
}: {
  username: string;
  counts: UserProfile["library_counts"];
  preview: LibraryEntry[];
  t: ProfileTranslator;
  tStatus: LibraryStatusTranslator;
  tType: BrowseTranslator;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-medium">{t("library.heading")}</h2>
        <Link href={`/u/${username}/library`} className="text-sm font-medium text-primary hover:underline">
          {t("library.viewAll")}
        </Link>
      </div>
      <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
        {LIBRARY_STATUSES.map((status) => (
          <span key={status}>
            {tStatus(status)}: {counts[status]}
          </span>
        ))}
      </div>
      {preview.length > 0 ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {preview.map((entry) => {
            const itemType = toCatalogType(entry.item.item_type);
            return (
              <CatalogCard
                key={`${entry.item.item_type}-${entry.item.slug}`}
                title={entry.item.title}
                posterUrl={entry.item.poster_url}
                ratingExternal={entry.item.rating_external}
                typeLabel={itemType ? tType(`heading.${itemType}`) : entry.item.item_type}
                href={itemType ? `/${itemType}/${entry.item.slug}` : undefined}
              />
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function ProfileReviewCard({
  review,
  locale,
  t,
}: {
  review: UserReview;
  locale: string;
  t: ProfileTranslator;
}) {
  const itemType = toCatalogType(review.item.item_type);
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
          <p className="text-xs text-muted-foreground">
            {t("reviews.dateLabel", { date: formatDate(review.created_at, locale) })}
          </p>
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

function ReviewStars({ score }: { score: number | null }) {
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

function ProfileListCard({ list, t }: { list: UserListSummary; t: ProfileTranslator }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-2">
        <p className="text-sm font-medium">{list.title}</p>
        {list.description ? (
          <p className="line-clamp-2 text-sm text-muted-foreground">{list.description}</p>
        ) : null}
        <p className="text-xs text-muted-foreground">
          {t("lists.itemCount", { count: list.item_count })}
        </p>
      </CardContent>
    </Card>
  );
}
