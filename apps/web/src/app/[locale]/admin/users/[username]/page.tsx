import { getTranslations, setRequestLocale } from "next-intl/server";
import Image from "next/image";
import { notFound } from "next/navigation";

import { AdminUserActionsPanel } from "@/components/admin-user-actions-panel";
import { buttonVariants } from "@/components/ui/button";
import { UserReviewCard } from "@/components/user-review-card";
import { Link } from "@/i18n/navigation";
import { getAdminUserDetail } from "@/lib/admin-users";
import { getCurrentUser } from "@/lib/api-fetch";
import { formatDate } from "@/lib/format-date";
import { getUserProfile, LIBRARY_STATUSES } from "@/lib/library";
import { getUserReviews } from "@/lib/user-content";
import { cn } from "@/lib/utils";

/** Same page size as `/u/{username}`'s own reviews section (FE-21). */
const REVIEWS_PAGE_SIZE = 10;

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parsePage(value: RawParam): number {
  const raw = firstValue(value);
  const parsed = raw ? Number.parseInt(raw, 10) : 1;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

/**
 * `/admin/users/{username}` (FE-33): a single user's full profile plus their
 * admin role/ban state and moderation actions — the destination every row of
 * `/admin/users`'s table (`AdminUsersDirectoryPanel`) links to. The
 * auth+`is_admin` gate lives in `@/app/[locale]/admin/layout.tsx`, which
 * wraps this route; nothing to check here beyond that.
 *
 * Three independent fetches, run in parallel:
 * - `getUserProfile` (`@/lib/library.ts`) — public `GET /v1/users/{username}`:
 *   bio, avatar, follower/following counts, `library_counts`.
 * - `getUserReviews` (`@/lib/user-content.ts`) — public, paginated
 *   `GET /v1/users/{username}/reviews`, same `page` query param convention as
 *   `/u/{username}` itself.
 * - `getAdminUserDetail` (`@/lib/admin-users.ts`) — admin-only
 *   `GET /v1/admin/users/{username}` (new in this feature): `is_admin`/
 *   `is_superadmin`/`is_banned`/`created_at`, none of which the public
 *   profile endpoint exposes.
 *
 * Only a confirmed 404 from EITHER `getUserProfile` or `getAdminUserDetail`
 * goes through `notFound()` — same `not-found`/`error` split every other
 * page in this app applies to its own primary data source
 * (`getItemDetail`'s doc comment, `/u/{username}`'s own `page.tsx`). A
 * transient admin-endpoint failure (wrong/unset `ADMIN_API_KEY`, backend
 * hiccup) degrades to an inline error in place of the badges/actions section
 * instead of failing the whole page — the public profile and reviews are
 * still valid and worth showing on their own.
 *
 * No `email` anywhere on this page — neither `UserOut` nor `AdminUserOut`
 * expose it (deliberate PII minimization, `docs/api.md`), and this feature
 * does not add a new way to read it.
 */
export default async function AdminUserDetailPage({
  params,
  searchParams,
}: PageProps<"/[locale]/admin/users/[username]">) {
  const { locale, username } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const page = parsePage(query.page);

  const [t, tLibraryStatus, profileResult, reviewsResult, adminResult, currentUser] = await Promise.all([
    getTranslations("Admin.userDetail"),
    getTranslations("Library.statusTabs"),
    getUserProfile(username),
    getUserReviews(username, { page, limit: REVIEWS_PAGE_SIZE }),
    getAdminUserDetail(username),
    getCurrentUser(),
  ]);

  if (profileResult.status === "not-found" || adminResult.status === "not-found") {
    notFound();
  }

  if (profileResult.status === "error") {
    return (
      <div className="flex flex-col gap-4">
        <p role="alert" className="text-sm text-destructive">
          {t("profileError")}
        </p>
      </div>
    );
  }

  const profile = profileResult.profile;
  const name = profile.display_name ?? profile.username;
  const totalReviewPages = reviewsResult.ok
    ? Math.max(1, Math.ceil(reviewsResult.total / reviewsResult.limit))
    : 1;
  const callerIsSuperadmin = currentUser?.is_superadmin ?? false;

  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            {profile.avatar_url ? (
              <Image
                src={profile.avatar_url}
                alt=""
                width={64}
                height={64}
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

          <Link href={`/u/${profile.username}`} className={cn(buttonVariants({ variant: "outline" }))}>
            {t("viewPublicProfile")}
          </Link>
        </div>

        {profile.bio ? <p className="max-w-2xl text-sm leading-6 text-foreground">{profile.bio}</p> : null}

        <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
          <span>{t("followerCount", { count: profile.follower_count })}</span>
          <span>{t("followingCount", { count: profile.following_count })}</span>
        </div>

        {adminResult.status === "ok" ? (
          <>
            <p className="text-sm text-muted-foreground">
              {t("joinedLabel", { date: formatDate(adminResult.user.created_at, locale) })}
            </p>
            <AdminUserActionsPanel
              username={profile.username}
              initialIsAdmin={adminResult.user.is_admin}
              initialIsBanned={adminResult.user.is_banned}
              isTargetSuperadmin={adminResult.user.is_superadmin}
              callerIsSuperadmin={callerIsSuperadmin}
            />
          </>
        ) : (
          <p role="alert" className="text-sm text-destructive">
            {t(`adminErrors.${adminResult.reason}`)}
          </p>
        )}
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-medium">{t("library.heading")}</h2>
        <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          {LIBRARY_STATUSES.map((status) => (
            <span key={status}>
              {tLibraryStatus(status)}: {profile.library_counts[status]}
            </span>
          ))}
        </div>
      </section>

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
                <UserReviewCard
                  key={review.id}
                  review={review}
                  locale={locale}
                  dateLabel={(date) => t("reviews.dateLabel", { date })}
                />
              ))}
            </div>
            <AdminUserReviewsPagination
              username={profile.username}
              page={page}
              totalPages={totalReviewPages}
              t={t}
            />
          </>
        )}
      </section>
    </div>
  );
}

type UserDetailTranslator = Awaited<ReturnType<typeof getTranslations<"Admin.userDetail">>>;

/**
 * Prev/next pagination for this page's reviews section — same shape as
 * `ProfileReviewsPagination` (`@/components/profile-reviews-pagination.tsx`),
 * not reused directly because that component hardcodes its target pathname
 * to `/u/{username}`, which doesn't apply here. Kept as a private helper
 * (like `/u/{username}`'s own review-card helpers were before this feature
 * extracted them) rather than a new shared component, since nothing else in
 * this app currently needs a `/admin/users/{username}`-targeted pager.
 */
function AdminUserReviewsPagination({
  username,
  page,
  totalPages,
  t,
}: {
  username: string;
  page: number;
  totalPages: number;
  t: UserDetailTranslator;
}) {
  if (totalPages <= 1) {
    return null;
  }

  function hrefFor(targetPage: number) {
    const query: Record<string, string> = {};
    if (targetPage > 1) {
      query.page = String(targetPage);
    }
    return { pathname: `/admin/users/${username}`, query };
  }

  const hasPrevious = page > 1;
  const hasNext = page < totalPages;

  return (
    <nav aria-label={t("reviews.pagination.nav")} className="flex items-center justify-between gap-4 pt-2">
      {hasPrevious ? (
        <Link href={hrefFor(page - 1)} className={cn(buttonVariants({ variant: "outline" }))}>
          {t("reviews.pagination.previous")}
        </Link>
      ) : (
        <span
          aria-disabled="true"
          className={cn(buttonVariants({ variant: "outline" }), "pointer-events-none opacity-50")}
        >
          {t("reviews.pagination.previous")}
        </span>
      )}

      <p className="text-sm text-muted-foreground">
        {t("reviews.pagination.pageStatus", { page, totalPages })}
      </p>

      {hasNext ? (
        <Link href={hrefFor(page + 1)} className={cn(buttonVariants({ variant: "outline" }))}>
          {t("reviews.pagination.next")}
        </Link>
      ) : (
        <span
          aria-disabled="true"
          className={cn(buttonVariants({ variant: "outline" }), "pointer-events-none opacity-50")}
        >
          {t("reviews.pagination.next")}
        </span>
      )}
    </nav>
  );
}
