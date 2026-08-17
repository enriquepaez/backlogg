"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Link, useRouter } from "@/i18n/navigation";
import { formatDate } from "@/lib/format-date";

import type { components } from "@backlogg/api-client";

type AdminUserOut = components["schemas"]["AdminUserOut"];

/** Same default page size as the BFF route's own `DEFAULT_LIMIT` (`../app/api/admin/users/route.ts`). */
const PAGE_LIMIT = 20;

const BANNED_FILTERS = ["all", "banned", "notBanned"] as const;
type BannedFilter = (typeof BANNED_FILTERS)[number];

const ADMIN_FILTERS = ["all", "admin", "notAdmin"] as const;
type AdminFilter = (typeof ADMIN_FILTERS)[number];

/**
 * Same debounce pattern as `SearchControls` (`@/components/search-controls.tsx`,
 * FE-11): wait this long after the user stops typing before committing the
 * trimmed value (and re-fetching) — a free-text field firing one request per
 * keystroke would be wasteful. 300ms instead of that component's 400ms since
 * this list has no external-API rate limit to protect, only the admin
 * backend's own DB query.
 */
const SEARCH_DEBOUNCE_MS = 300;

type UsersResponse = { items: AdminUserOut[]; total: number; page: number; limit: number };

type PanelState =
  | { status: "loading" }
  | { status: "loaded"; items: AdminUserOut[]; total: number }
  | { status: "error"; reason: "unauthorized" | "not_configured" | "unknown" };

type UsersDirectoryTranslator = ReturnType<typeof useTranslations<"Admin.usersDirectory">>;

/**
 * Client Component (FE-33, rewritten from the FE-30-era version): paginated,
 * filterable, READ-ONLY admin user directory, fetched from
 * `GET /api/admin/users?is_banned=&is_admin=&search=&page=&limit=`
 * (`@/app/api/admin/users/route.ts`) — same base shape as `AdminReportsPanel`
 * (FE-29): loading/loaded/error states, generic `unauthorized`/
 * `not_configured`/`unknown` error reasons relayed 1:1 from the Route
 * Handler, local (not URL-synced) `page`/filter state for the same reason
 * `AdminReportsPanel` keeps its own local `page`/`filter` — this panel
 * fetches its own data client-side against a BFF route that itself requires
 * a server-only secret, so there is no server-rendered variant to keep a URL
 * in sync with.
 *
 * Renders a real `<table>` (`@/components/ui/table.tsx`, first use of this
 * shadcn primitive in the app) instead of the previous version's cards, and
 * no longer exposes ban/unban or grant/revoke-admin inline per row — those
 * four actions (and the `isSuperadmin`-gated visibility rule for the role
 * pair) moved wholesale to `/admin/users/{username}`'s own actions panel
 * (`@/components/admin-user-actions-panel.tsx`), reusing the exact same
 * `@/lib/admin-user-actions.ts` helper this panel used to call directly.
 * This panel now only needs enough of `AdminUserOut` to render three status
 * badges (Admin/Superadmin/Banned) and a joined date — no `isSuperadmin`
 * prop, no pending/confirm state, no toasts.
 *
 * The filter bar (post-QA-feedback rework: the two ban/role filters used to
 * be two visually-identical pill `role="tablist"` rows) is now three clearly
 * distinct controls — a debounced free-text search `Input` plus two real
 * `Select`s (`@/components/ui/select.tsx`, first use of this shadcn
 * primitive in the app), each with a visible text `Label` above it (not just
 * an `aria-label`) so ban status and role read as different filters at a
 * glance, not just to a screen reader. `search` matches username, display
 * name, or email on the backend (`docs/api.md`) but `AdminUserOut` never
 * exposes `email`, matching this app's existing PII-minimization stance.
 *
 * Each row navigates to `/admin/users/{username}` on click (`useRouter`,
 * `@/i18n/navigation`) — the username cell also renders a real `<Link>` so
 * the destination is keyboard/screen-reader reachable without relying on the
 * row's `onClick` alone.
 */
export function AdminUsersDirectoryPanel() {
  const t = useTranslations("Admin.usersDirectory");
  const locale = useLocale();
  const router = useRouter();

  const [bannedFilter, setBannedFilter] = useState<BannedFilter>("all");
  const [adminFilter, setAdminFilter] = useState<AdminFilter>("all");
  const [searchInput, setSearchInput] = useState("");
  // The last debounced/committed value the fetch effect below actually uses
  // — kept separate from `searchInput` (the raw, every-keystroke value) so
  // typing doesn't refetch on every character.
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [state, setState] = useState<PanelState>({ status: "loading" });

  // Same debounce shape as `SearchControls`' own effect: compare the trimmed
  // local value against the last committed one and no-op if they already
  // match (covers the initial render, where both start as `""`), only
  // scheduling a commit for a genuine, still-pending edit.
  useEffect(() => {
    const trimmed = searchInput.trim();
    if (trimmed === search) return;
    const handle = setTimeout(() => {
      setSearch(trimmed);
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setState({ status: "loading" });
      try {
        const params = new URLSearchParams({ page: String(page), limit: String(PAGE_LIMIT) });
        if (bannedFilter !== "all") {
          params.set("is_banned", bannedFilter === "banned" ? "true" : "false");
        }
        if (adminFilter !== "all") {
          params.set("is_admin", adminFilter === "admin" ? "true" : "false");
        }
        if (search !== "") {
          params.set("search", search);
        }
        const response = await fetch(`/api/admin/users?${params.toString()}`);
        if (cancelled) return;

        if (response.status === 200) {
          const data = (await response.json()) as UsersResponse;
          setState({ status: "loaded", items: data.items, total: data.total });
          return;
        }
        if (response.status === 401) {
          setState({ status: "error", reason: "unauthorized" });
          return;
        }
        if (response.status === 503) {
          setState({ status: "error", reason: "not_configured" });
          return;
        }
        setState({ status: "error", reason: "unknown" });
      } catch {
        if (!cancelled) {
          setState({ status: "error", reason: "unknown" });
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [bannedFilter, adminFilter, search, page]);

  function changeBannedFilter(next: BannedFilter) {
    if (next === bannedFilter) return;
    setBannedFilter(next);
    setPage(1);
  }

  function changeAdminFilter(next: AdminFilter) {
    if (next === adminFilter) return;
    setAdminFilter(next);
    setPage(1);
  }

  function goToDetail(username: string) {
    router.push(`/admin/users/${encodeURIComponent(username)}`);
  }

  const totalPages = state.status === "loaded" ? Math.max(1, Math.ceil(state.total / PAGE_LIMIT)) : 1;

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-medium">{t("heading")}</h2>
      <p className="text-sm text-muted-foreground">{t("description")}</p>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:gap-4">
        <div className="flex min-w-56 flex-1 flex-col gap-1.5">
          <Label htmlFor="users-directory-search">{t("filters.search.label")}</Label>
          <Input
            id="users-directory-search"
            type="search"
            placeholder={t("filters.search.placeholder")}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="users-directory-banned-filter">{t("filters.banned.label")}</Label>
          <Select value={bannedFilter} onValueChange={(value) => changeBannedFilter(value as BannedFilter)}>
            <SelectTrigger id="users-directory-banned-filter" className="sm:w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BANNED_FILTERS.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`filters.banned.${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="users-directory-admin-filter">{t("filters.admin.label")}</Label>
          <Select value={adminFilter} onValueChange={(value) => changeAdminFilter(value as AdminFilter)}>
            <SelectTrigger id="users-directory-admin-filter" className="sm:w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ADMIN_FILTERS.map((value) => (
                <SelectItem key={value} value={value}>
                  {t(`filters.admin.${value}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {state.status === "loaded" ? (
        <p className="text-sm text-muted-foreground">
          {t("resultsCount", { shown: state.items.length, total: state.total })}
        </p>
      ) : null}

      {state.status === "loading" ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t("loading")}
        </p>
      ) : state.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {t(`errors.${state.reason}`)}
        </p>
      ) : state.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("columns.user")}</TableHead>
                <TableHead>{t("columns.status")}</TableHead>
                <TableHead>{t("columns.joined")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {state.items.map((item) => (
                <UserRow key={item.username} item={item} locale={locale} onNavigate={goToDetail} t={t} />
              ))}
            </TableBody>
          </Table>

          {totalPages > 1 ? (
            <nav
              aria-label={t("pagination.nav")}
              className="flex items-center justify-between gap-4 pt-2"
            >
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((current) => current - 1)}
              >
                {t("pagination.previous")}
              </Button>
              <p className="text-sm text-muted-foreground">
                {t("pagination.pageStatus", { page, totalPages })}
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((current) => current + 1)}
              >
                {t("pagination.next")}
              </Button>
            </nav>
          ) : null}
        </>
      )}
    </section>
  );
}

function UserRow({
  item,
  locale,
  onNavigate,
  t,
}: {
  item: AdminUserOut;
  locale: string;
  onNavigate: (username: string) => void;
  t: UsersDirectoryTranslator;
}) {
  return (
    <TableRow className="cursor-pointer" onClick={() => onNavigate(item.username)}>
      <TableCell>
        <div className="flex flex-col gap-0.5">
          <Link
            href={`/admin/users/${item.username}`}
            onClick={(event) => event.stopPropagation()}
            className="w-fit text-sm font-medium text-foreground hover:underline"
          >
            {item.display_name ?? item.username}
          </Link>
          <span className="text-xs text-muted-foreground">@{item.username}</span>
        </div>
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1.5">
          {item.is_superadmin ? (
            <span className="w-fit rounded-full bg-purple-500/10 px-2.5 py-0.5 text-xs font-medium text-purple-600">
              {t("badges.superadmin")}
            </span>
          ) : item.is_admin ? (
            <span className="w-fit rounded-full bg-blue-500/10 px-2.5 py-0.5 text-xs font-medium text-blue-600">
              {t("badges.admin")}
            </span>
          ) : null}
          {item.is_banned ? (
            <span className="w-fit rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs font-medium text-destructive">
              {t("badges.banned")}
            </span>
          ) : null}
        </div>
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {formatDate(item.created_at, locale)}
      </TableCell>
    </TableRow>
  );
}
