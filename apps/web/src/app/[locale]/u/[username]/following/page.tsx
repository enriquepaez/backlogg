import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { FollowPagination } from "@/components/follow-pagination";
import { FollowUserList } from "@/components/follow-user-list";
import { Link } from "@/i18n/navigation";
import { getFollowing } from "@/lib/follows";
import { getUserProfile } from "@/lib/library";

/** Page size for this list — matches the backend's own default (`backlogg/follows/routes.py`, `default=20`). */
const FOLLOW_PAGE_SIZE = 20;

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
 * Public "following" list for one user (FE-23), `/u/{username}/following`.
 * Sibling of `followers/page.tsx` — identical shape, `getFollowing` instead
 * of `getFollowers`. See that file's doc comment.
 */
export default async function UserFollowingPage({
  params,
  searchParams,
}: PageProps<"/[locale]/u/[username]/following">) {
  const { locale, username } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const page = parsePage(query.page);

  const [t, profileResult, result] = await Promise.all([
    getTranslations("Follows"),
    getUserProfile(username),
    getFollowing(username, { page, limit: FOLLOW_PAGE_SIZE }),
  ]);

  if (profileResult.status === "not-found") {
    notFound();
  }

  if (profileResult.status === "error") {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-6 py-16">
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      </div>
    );
  }

  const profile = profileResult.profile;
  const totalPages = result.ok ? Math.max(1, Math.ceil(result.total / result.limit)) : 1;

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8 px-6 py-16">
      <div className="flex flex-col gap-2">
        <Link href={`/u/${username}`} className="text-sm font-medium text-primary hover:underline">
          {t("backToProfile")}
        </Link>
        <h1 className="text-3xl font-semibold tracking-tight">
          {t("followingHeading", { name: profile.display_name ?? profile.username })}
        </h1>
      </div>

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("emptyFollowing")}</p>
      ) : (
        <>
          <FollowUserList users={result.items} />
          <FollowPagination href={`/u/${username}/following`} page={result.page} totalPages={totalPages} />
        </>
      )}
    </div>
  );
}
