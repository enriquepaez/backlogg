import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { CatalogCard } from "@/components/catalog-card";
import { LibraryPagination } from "@/components/library-pagination";
import { Link } from "@/i18n/navigation";
import { CATALOG_TYPES, isCatalogType, type CatalogType } from "@/lib/catalog-types";
import {
  getUserLibrary,
  getUserProfile,
  isLibraryStatus,
  LIBRARY_STATUSES,
  STATUS_COLOR_CLASSES,
  type LibraryStatusValue,
  type UserProfile,
} from "@/lib/library";
import { toCatalogType } from "@/lib/search";
import { cn } from "@/lib/utils";

/** Page size for the library grid — matches `BROWSE_PAGE_SIZE`/`SEARCH_PAGE_SIZE` for a consistent grid layout. */
export const LIBRARY_PAGE_SIZE = 24;

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseStatus(value: RawParam): LibraryStatusValue | undefined {
  const raw = firstValue(value);
  return raw && isLibraryStatus(raw) ? raw : undefined;
}

function parseType(value: RawParam): CatalogType | undefined {
  const raw = firstValue(value);
  return raw && isCatalogType(raw) ? raw : undefined;
}

function parsePage(value: RawParam): number {
  const raw = firstValue(value);
  const parsed = raw ? Number.parseInt(raw, 10) : 1;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

type LibraryTranslator = Awaited<ReturnType<typeof getTranslations<"Library">>>;

/**
 * Status filter tabs, with per-status counts from `UserOut.library_counts`
 * (zero-filled, `docs/api.md`) — no fetch needed beyond the profile already
 * loaded for the page heading. Plain server-rendered `Link`s (works with JS
 * disabled), same rationale as `LibraryPagination`/`BrowsePagination`; kept
 * inline here rather than split into their own file+test since — unlike
 * `LibraryPagination`'s reusable prev/next math — this is a straightforward
 * list of five links with no behavior worth unit-testing on its own (no page
 * component in this codebase has its own `page.test.tsx` either, see
 * `browse/[type]/page.tsx`/`search/page.tsx`).
 */
function StatusTabs({
  username,
  status,
  type,
  counts,
  t,
}: {
  username: string;
  status: LibraryStatusValue | undefined;
  type: CatalogType | undefined;
  counts: UserProfile["library_counts"];
  t: LibraryTranslator;
}) {
  function hrefFor(targetStatus: LibraryStatusValue | undefined) {
    const query: Record<string, string> = {};
    if (targetStatus) query.status = targetStatus;
    if (type) query.type = type;
    return { pathname: `/u/${username}/library`, query };
  }

  const tabs: Array<{ value: LibraryStatusValue | undefined; label: string }> = [
    { value: undefined, label: t("statusTabs.all") },
    ...LIBRARY_STATUSES.map((value) => ({ value, label: t(`statusTabs.${value}`) })),
  ];

  return (
    <div role="tablist" aria-label={t("statusTabs.label")} className="flex flex-wrap gap-2">
      {tabs.map((tab) => {
        const isActive = tab.value === status;
        const count = tab.value ? counts[tab.value] : undefined;
        return (
          <Link
            key={tab.label}
            href={hrefFor(tab.value)}
            role="tab"
            aria-selected={isActive}
            className={cn(
              "rounded-full border px-3 py-1 text-sm font-medium transition-colors",
              isActive
                ? tab.value
                  ? `border-transparent ${STATUS_COLOR_CLASSES[tab.value]}`
                  : "border-transparent bg-primary text-primary-foreground"
                : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            {count !== undefined ? t("statusTabs.withCount", { label: tab.label, count }) : tab.label}
          </Link>
        );
      })}
    </div>
  );
}

/**
 * Type filter tabs — same shape as `StatusTabs` but without counts: the
 * backend's `library_counts` isn't broken down per content type
 * (`docs/api.md`), only per status.
 */
function TypeTabs({
  username,
  status,
  type,
  t,
}: {
  username: string;
  status: LibraryStatusValue | undefined;
  type: CatalogType | undefined;
  t: LibraryTranslator;
}) {
  function hrefFor(targetType: CatalogType | undefined) {
    const query: Record<string, string> = {};
    if (status) query.status = status;
    if (targetType) query.type = targetType;
    return { pathname: `/u/${username}/library`, query };
  }

  const tabs: Array<{ value: CatalogType | undefined; label: string }> = [
    { value: undefined, label: t("typeTabs.all") },
    ...CATALOG_TYPES.map((value) => ({ value, label: t(`typeTabs.${value}`) })),
  ];

  return (
    <div role="tablist" aria-label={t("typeTabs.label")} className="flex flex-wrap gap-2">
      {tabs.map((tab) => {
        const isActive = tab.value === type;
        return (
          <Link
            key={tab.label}
            href={hrefFor(tab.value)}
            role="tab"
            aria-selected={isActive}
            className={cn(
              "rounded-full border px-3 py-1 text-sm font-medium transition-colors",
              isActive
                ? "border-transparent bg-primary text-primary-foreground"
                : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}

/**
 * Public library/backlog page for one user (FE-20), `/u/{username}/library`.
 * Sibling of `/u/{username}` (the full profile, FE-21), which links here for
 * its own "view full library" summary section rather than duplicating this
 * grid.
 *
 * Loads the profile (`getUserProfile`, for the heading + `library_counts`)
 * and the filtered/paginated library (`getUserLibrary`) — both public,
 * `@/lib/library`. Only a backend-confirmed 404 username goes through
 * `notFound()`, same `not-found`/`error` split as the item detail page
 * (`getItemDetail`'s doc comment, `src/lib/catalog.ts`).
 */
export default async function UserLibraryPage({
  params,
  searchParams,
}: PageProps<"/[locale]/u/[username]/library">) {
  const { locale, username } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const status = parseStatus(query.status);
  const type = parseType(query.type);
  const page = parsePage(query.page);

  const [t, tType, profileResult] = await Promise.all([
    getTranslations("Library"),
    getTranslations("Browse"),
    getUserProfile(username),
  ]);

  if (profileResult.status === "not-found") {
    notFound();
  }

  if (profileResult.status === "error") {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-16">
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      </div>
    );
  }

  const profile = profileResult.profile;

  const result = await getUserLibrary(username, { status, type, page, limit: LIBRARY_PAGE_SIZE });
  const totalPages = result.ok ? Math.max(1, Math.ceil(result.total / result.limit)) : 1;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">
        {t("heading", { name: profile.display_name ?? profile.username })}
      </h1>

      <div className="flex flex-col gap-3">
        <StatusTabs
          username={username}
          status={status}
          type={type}
          counts={profile.library_counts}
          t={t}
        />
        <TypeTabs username={username} status={status} type={type} t={t} />
      </div>

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {result.items.map((entry) => {
              const itemType = toCatalogType(entry.item.item_type);
              const entryStatus = isLibraryStatus(entry.status) ? entry.status : undefined;
              return (
                <CatalogCard
                  key={`${entry.item.item_type}-${entry.item.slug}`}
                  title={entry.item.title}
                  posterUrl={entry.item.poster_url}
                  ratingExternal={entry.item.rating_external}
                  typeLabel={itemType ? tType(`heading.${itemType}`) : entry.item.item_type}
                  libraryStatus={entryStatus}
                  libraryStatusLabel={entryStatus ? t(`statusTabs.${entryStatus}`) : undefined}
                  href={itemType ? `/${itemType}/${entry.item.slug}` : undefined}
                />
              );
            })}
          </div>

          <LibraryPagination
            username={username}
            status={status}
            type={type}
            page={result.page}
            totalPages={totalPages}
          />
        </>
      )}
    </div>
  );
}
