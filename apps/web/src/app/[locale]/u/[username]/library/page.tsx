import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { CatalogCard } from "@/components/catalog-card";
import { LibraryBoard } from "@/components/library-board";
import { LibraryPagination } from "@/components/library-pagination";
import { LibrarySortSelect } from "@/components/library-sort";
import { LibraryViewToggle } from "@/components/library-view-toggle";
import { Link } from "@/i18n/navigation";
import { getCurrentUser } from "@/lib/api-fetch";
import { CATALOG_TYPES, isCatalogType, type CatalogType } from "@/lib/catalog-types";
import {
  DEFAULT_LIBRARY_SORT,
  DEFAULT_LIBRARY_VIEW,
  getUserLibrary,
  getUserProfile,
  getUserReviewScores,
  isLibrarySort,
  isLibraryStatus,
  isLibraryView,
  LIBRARY_STATUSES,
  sortLibraryEntries,
  STATUS_COLOR_CLASSES,
  type LibraryEntry,
  type LibrarySort,
  type LibraryStatusValue,
  type LibraryView,
  type UserProfile,
} from "@/lib/library";
import { toCatalogType } from "@/lib/search";
import { cn } from "@/lib/utils";

/** Page size for the library grid — matches `BROWSE_PAGE_SIZE`/`SEARCH_PAGE_SIZE` for a consistent grid layout. */
export const LIBRARY_PAGE_SIZE = 24;

/**
 * Cap on how many entries the board view (FE-43) fetches in one shot —
 * the backend's own max `limit` for `GET /v1/users/{username}/library`
 * (`docs/api.md`, `le=100`), same ceiling `getUserReviewScores`'s
 * `REVIEW_SCORE_SCAN_LIMIT` already documents for the same endpoint family.
 * Unlike the grid, the board isn't paginated — all four columns render from
 * one fetch — so on a library with more than this many entries the board
 * silently only shows the most recently created/updated ones (the backend's
 * default order); the grid remains the only way to reach older entries past
 * that point. See `resolveBoardColumns`'s doc comment for how each column's
 * displayed *count* still avoids this cap wherever possible.
 */
const LIBRARY_BOARD_SCAN_LIMIT = 100;

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

function parseSort(value: RawParam): LibrarySort {
  const raw = firstValue(value);
  return raw && isLibrarySort(raw) ? raw : DEFAULT_LIBRARY_SORT;
}

/** Unlike the other `parse*` helpers, returns `undefined` (not a default) when `?view=` is absent — `page.tsx` needs to tell "no `view` in the URL" apart from "`view=grid` explicitly", see `LibraryViewToggle`'s `hasExplicitView` prop. */
function parseView(value: RawParam): LibraryView | undefined {
  const raw = firstValue(value);
  return raw && isLibraryView(raw) ? raw : undefined;
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
  sort,
  counts,
  t,
}: {
  username: string;
  status: LibraryStatusValue | undefined;
  type: CatalogType | undefined;
  sort: LibrarySort;
  counts: UserProfile["library_counts"];
  t: LibraryTranslator;
}) {
  function hrefFor(targetStatus: LibraryStatusValue | undefined) {
    const query: Record<string, string> = {};
    if (targetStatus) query.status = targetStatus;
    if (type) query.type = type;
    if (sort !== DEFAULT_LIBRARY_SORT) query.sort = sort;
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
  sort,
  t,
}: {
  username: string;
  status: LibraryStatusValue | undefined;
  type: CatalogType | undefined;
  sort: LibrarySort;
  t: LibraryTranslator;
}) {
  function hrefFor(targetType: CatalogType | undefined) {
    const query: Record<string, string> = {};
    if (status) query.status = status;
    if (targetType) query.type = targetType;
    if (sort !== DEFAULT_LIBRARY_SORT) query.sort = sort;
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
 * Groups+sorts one board fetch's entries into a column per
 * {@link LibraryStatusValue} (FE-43) and works out each column's displayed
 * count. `entries` come from a single `getUserLibrary` call with no `status`
 * filter (the board always shows all four columns at once — see
 * `page.tsx`'s module doc comment for why the status filter doesn't apply in
 * board view) capped at {@link LIBRARY_BOARD_SCAN_LIMIT}.
 *
 * The count next to each header is the exact `libraryCounts[status]` (from
 * `UserOut.library_counts`, unaffected by the fetch cap) whenever no `type`
 * filter narrows the board — `type` is `undefined` in that case. When a
 * `type` filter *is* active, `library_counts` can't help (it isn't broken
 * down per type), so the count falls back to however many matching entries
 * this capped fetch actually returned, same "may under-count past the cap"
 * caveat as {@link LIBRARY_BOARD_SCAN_LIMIT}.
 */
function resolveBoardColumns(
  entries: LibraryEntry[],
  sort: LibrarySort,
  scores: Map<string, number> | undefined,
  libraryCounts: UserProfile["library_counts"],
  type: CatalogType | undefined,
): { entriesByStatus: Record<LibraryStatusValue, LibraryEntry[]>; countsByStatus: Record<LibraryStatusValue, number> } {
  const grouped = Object.fromEntries(
    LIBRARY_STATUSES.map((status) => [status, entries.filter((entry) => entry.status === status)]),
  ) as Record<LibraryStatusValue, LibraryEntry[]>;

  const entriesByStatus = Object.fromEntries(
    LIBRARY_STATUSES.map((status) => [status, sortLibraryEntries(grouped[status], sort, scores)]),
  ) as Record<LibraryStatusValue, LibraryEntry[]>;

  const countsByStatus = Object.fromEntries(
    LIBRARY_STATUSES.map((status) => [status, type ? grouped[status].length : libraryCounts[status]]),
  ) as Record<LibraryStatusValue, number>;

  return { entriesByStatus, countsByStatus };
}

/**
 * OG metadata for the public library page (FE-45) — same pattern as the
 * profile page's own `generateMetadata` (`../page.tsx`), with its own
 * `Metadata.profileLibrary` copy ("{name}'s library") rather than reusing
 * `Metadata.profile`. `{}`-on-non-`ok` degrade and the `avatar_url`-or-
 * generic-`/opengraph-image` fallback are identical — see that sibling's
 * doc comment for the rationale.
 */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/u/[username]/library">): Promise<Metadata> {
  const { locale, username } = await params;
  const result = await getUserProfile(username);
  if (result.status !== "ok") {
    return {};
  }

  const profile = result.profile;
  const name = profile.display_name ?? profile.username;
  const tm = await getTranslations({ locale, namespace: "Metadata.profileLibrary" });
  const title = tm("title", { name });
  const description = tm("description", { name });

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      type: "website",
      images: [profile.avatar_url ?? "/opengraph-image"],
    },
  };
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
 *
 * `sort` (FE-38) is applied client-side, in this component, via
 * `sortLibraryEntries` over the single already-fetched page of `result.items`
 * — the backend's `GET /v1/users/{username}/library` has no `sort` query
 * param at all (see `LibrarySort`'s doc comment, `@/lib/library-types`).
 * `getUserReviewScores` (the extra per-item "your rating" lookup
 * `rating_desc` needs) is only fetched when that sort is actually selected,
 * in parallel with `getUserLibrary` — every other sort needs no extra
 * request.
 *
 * `view` (FE-43, `?view=grid|board`) picks between this flat grid and a
 * four-column board (`LibraryBoard`), and is only ever resolved to `"board"`
 * for the viewer's own library (`isOwnLibrary`, from `getCurrentUser`) —
 * someone else's library always renders `"grid"`, read-only, and never gets
 * the `LibraryViewToggle` control at all, regardless of any `?view=` a URL
 * might carry. Board mode changes two other filters' behavior, both
 * documented here rather than hidden:
 * - `StatusTabs` is omitted entirely — the board already shows all four
 *   statuses side by side, so filtering to one status would leave three
 *   columns permanently empty for no benefit over just switching back to
 *   the grid.
 * - `LibraryPagination` is omitted — the board isn't paginated, it fetches
 *   up to `LIBRARY_BOARD_SCAN_LIMIT` entries in one shot (see that
 *   constant's doc comment) and lays every column out in full.
 * `TypeTabs` and `LibrarySortSelect` keep working unmodified in both modes.
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
  const sort = parseSort(query.sort);
  const explicitView = parseView(query.view);

  const [t, tType, profileResult, currentUser] = await Promise.all([
    getTranslations("Library"),
    getTranslations("Browse"),
    getUserProfile(username),
    getCurrentUser(),
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
  const isOwnLibrary = currentUser?.username === username;
  const view: LibraryView = isOwnLibrary ? (explicitView ?? DEFAULT_LIBRARY_VIEW) : DEFAULT_LIBRARY_VIEW;
  const isBoardView = view === "board";

  const [result, scores] = await Promise.all([
    isBoardView
      ? getUserLibrary(username, { type, limit: LIBRARY_BOARD_SCAN_LIMIT })
      : getUserLibrary(username, { status, type, page, limit: LIBRARY_PAGE_SIZE }),
    sort === "rating_desc" ? getUserReviewScores(username) : Promise.resolve(undefined),
  ]);
  const totalPages = result.ok ? Math.max(1, Math.ceil(result.total / result.limit)) : 1;
  const items = result.ok ? sortLibraryEntries(result.items, sort, scores) : [];
  const board = result.ok
    ? resolveBoardColumns(result.items, sort, scores, profile.library_counts, type)
    : undefined;
  const isEmpty = isBoardView
    ? !board || LIBRARY_STATUSES.every((s) => board.entriesByStatus[s].length === 0)
    : items.length === 0;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-semibold tracking-tight">
          {t("heading", { name: profile.display_name ?? profile.username })}
        </h1>
        {isOwnLibrary ? (
          <LibraryViewToggle
            username={username}
            status={status}
            type={type}
            sort={sort}
            view={view}
            hasExplicitView={explicitView !== undefined}
          />
        ) : null}
      </div>

      <div className="flex flex-col gap-3">
        {isBoardView ? null : (
          <StatusTabs
            username={username}
            status={status}
            type={type}
            sort={sort}
            counts={profile.library_counts}
            t={t}
          />
        )}
        <TypeTabs username={username} status={status} type={type} sort={sort} t={t} />
        <LibrarySortSelect username={username} status={status} type={type} selectedSort={sort} />
      </div>

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : isEmpty ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : isBoardView && board ? (
        <LibraryBoard entriesByStatus={board.entriesByStatus} countsByStatus={board.countsByStatus} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {items.map((entry) => {
              const itemType = toCatalogType(entry.item.item_type);
              const entryStatus = isLibraryStatus(entry.status) ? entry.status : undefined;
              return (
                <CatalogCard
                  key={`${entry.item.item_type}-${entry.item.slug}`}
                  title={entry.item.title}
                  posterUrl={entry.item.poster_url}
                  ratingInternal={entry.item.rating_internal}
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
            sort={sort}
            page={result.page}
            totalPages={totalPages}
          />
        </>
      )}
    </div>
  );
}
