"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatDate } from "@/lib/format-date";
import { cn } from "@/lib/utils";

import type { components } from "@backlogg/api-client";

type ReportOut = components["schemas"]["ReportOut"];

/** Same default page size as the BFF route's own `DEFAULT_LIMIT` (`../app/api/admin/reports/route.ts`). */
const PAGE_LIMIT = 20;

const STATUS_FILTERS = ["all", "open", "resolved"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

type ReportsResponse = { items: ReportOut[]; total: number; page: number; limit: number };

type PanelState =
  | { status: "loading" }
  | { status: "loaded"; items: ReportOut[]; total: number }
  | { status: "error"; reason: "unauthorized" | "not_configured" | "unknown" };

type ReportsTranslator = ReturnType<typeof useTranslations<"Admin.reports">>;

/**
 * Client Component (FE-29): moderation queue for reported reviews, fetched
 * from `GET /api/admin/reports?status=&page=&limit=`
 * (`@/app/api/admin/reports/route.ts`) — same base shape as
 * `AdminStatsPanel` (FE-28): loading/loaded/error states, generic
 * `unauthorized`/`not_configured`/`unknown` error reasons relayed 1:1 from
 * the Route Handler, which is the only place that ever sees the real
 * `X-API-Key`.
 *
 * `filter`/`page` are local component state, not URL query params — same
 * choice `ItemReviews` (`item-reviews.tsx`, FE-19) makes for its own
 * pagination, and for the same reason: this panel fetches its own data
 * client-side against a BFF route that itself requires a server-only secret,
 * so there is no server-rendered variant of this list to keep in sync with a
 * URL in the first place.
 *
 * `ReportOut` only carries `rating_id` (`docs/api.md`), not the reported
 * item's `type`/`slug` or review text — there is no public route in this app
 * navigable by a bare rating id (`docs/schema.md`'s item detail pages are
 * keyed by `type`/`slug`, not `user_ratings.id`), so this panel shows the
 * rating id as plain text (`reviewLabel`) rather than inventing a route that
 * doesn't exist. See `progress/impl_report_queue.md` for the full rationale.
 *
 * Resolving a report (`POST /api/admin/reports/{id}/resolve`) refetches the
 * current page on success rather than patching the item in place: the
 * backend queue is newest-first and un-filtered pages can shrink once an
 * `open` report leaves that bucket, so a full refetch is the only way to
 * keep `total`/pagination consistent with the `status` filter in view.
 *
 * Hide/unhide (FE-30, `POST /api/admin/reviews/{ratingId}/hide` /
 * `/unhide`) is the exception: it acts on the *reviewed rating*
 * (`report.rating_id`), not the report itself, so it never changes which
 * page/filter bucket a report belongs to — no refetch needed. Instead this
 * component tracks the known `is_hidden` state per rating id
 * (`hiddenByRatingId`) in local state, seeded from each hide/unhide
 * response (`ReviewModerationOut`, `docs/api.md`) — `ReportOut` itself
 * carries no `is_hidden` field, so this state starts unknown per rating id
 * until the admin acts on it at least once, at which point the card's
 * "Hide"/"Unhide" toggle and status badge switch to reflect the response,
 * which is the "refresh after each action" requirement for this specific
 * action.
 */
export function AdminReportsPanel() {
  const t = useTranslations("Admin.reports");
  const locale = useLocale();

  const [filter, setFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);
  const [state, setState] = useState<PanelState>({ status: "loading" });
  const [resolvingId, setResolvingId] = useState<number | null>(null);
  const [hiddenByRatingId, setHiddenByRatingId] = useState<Record<number, boolean>>({});
  const [togglingRatingId, setTogglingRatingId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setState({ status: "loading" });
      try {
        const params = new URLSearchParams({ page: String(page), limit: String(PAGE_LIMIT) });
        if (filter !== "all") {
          params.set("status", filter);
        }
        const response = await fetch(`/api/admin/reports?${params.toString()}`);
        if (cancelled) return;

        if (response.status === 200) {
          const data = (await response.json()) as ReportsResponse;
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
  }, [filter, page, reloadKey]);

  function changeFilter(next: StatusFilter) {
    if (next === filter) return;
    setFilter(next);
    setPage(1);
  }

  async function handleResolve(reportId: number) {
    if (resolvingId !== null) return;
    setResolvingId(reportId);

    try {
      const response = await fetch(`/api/admin/reports/${reportId}/resolve`, {
        method: "POST",
      });
      if (response.status === 200) {
        toast.success(t("resolveSuccess"));
        setReloadKey((key) => key + 1);
      } else {
        toast.error(t("resolveError"));
      }
    } catch {
      toast.error(t("resolveError"));
    } finally {
      setResolvingId(null);
    }
  }

  async function handleToggleHide(ratingId: number, nextHidden: boolean) {
    if (togglingRatingId !== null) return;
    setTogglingRatingId(ratingId);

    try {
      const response = await fetch(
        `/api/admin/reviews/${ratingId}/${nextHidden ? "hide" : "unhide"}`,
        { method: "POST" },
      );
      if (response.status === 200) {
        const data = (await response.json()) as { id: number; is_hidden: boolean };
        setHiddenByRatingId((current) => ({ ...current, [ratingId]: data.is_hidden }));
        toast.success(nextHidden ? t("hideSuccess") : t("unhideSuccess"));
      } else {
        toast.error(nextHidden ? t("hideError") : t("unhideError"));
      }
    } catch {
      toast.error(nextHidden ? t("hideError") : t("unhideError"));
    } finally {
      setTogglingRatingId(null);
    }
  }

  const totalPages = state.status === "loaded" ? Math.max(1, Math.ceil(state.total / PAGE_LIMIT)) : 1;

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-medium">{t("heading")}</h2>

      <div role="tablist" aria-label={t("filters.label")} className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((value) => {
          const isActive = value === filter;
          return (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => changeFilter(value)}
              className={cn(
                "rounded-full border px-3 py-1 text-sm font-medium transition-colors",
                isActive
                  ? "border-transparent bg-primary text-primary-foreground"
                  : "border-border bg-background text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`filters.${value}`)}
            </button>
          );
        })}
      </div>

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
          <div className="flex flex-col gap-4">
            {state.items.map((report) => (
              <ReportCard
                key={report.id}
                report={report}
                locale={locale}
                resolving={resolvingId === report.id}
                onResolve={() => handleResolve(report.id)}
                isHidden={hiddenByRatingId[report.rating_id]}
                togglingHide={togglingRatingId === report.rating_id}
                onToggleHide={(nextHidden) => handleToggleHide(report.rating_id, nextHidden)}
                t={t}
              />
            ))}
          </div>

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

function ReportCard({
  report,
  locale,
  resolving,
  onResolve,
  isHidden,
  togglingHide,
  onToggleHide,
  t,
}: {
  report: ReportOut;
  locale: string;
  resolving: boolean;
  onResolve: () => void;
  isHidden: boolean | undefined;
  togglingHide: boolean;
  onToggleHide: (nextHidden: boolean) => void;
  t: ReportsTranslator;
}) {
  const isOpen = report.status === "open";
  /** Unknown until the admin acts on it at least once — see this component's own doc comment. */
  const hideActionLabel = isHidden ? t("unhideAction") : t("hideAction");

  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-foreground">
              {t("reviewLabel", { ratingId: report.rating_id })}
            </p>
            <div className="flex flex-wrap gap-1.5">
              <span
                className={cn(
                  "w-fit rounded-full px-2.5 py-0.5 text-xs font-medium",
                  isOpen
                    ? "bg-amber-500/10 text-amber-600"
                    : "bg-green-500/10 text-green-600",
                )}
              >
                {t(isOpen ? "status.open" : "status.resolved")}
              </span>
              {isHidden !== undefined ? (
                <span
                  className={cn(
                    "w-fit rounded-full px-2.5 py-0.5 text-xs font-medium",
                    isHidden
                      ? "bg-destructive/10 text-destructive"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {t(isHidden ? "reviewHidden" : "reviewVisible")}
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 text-xs text-muted-foreground">
            <p>{t("createdAtLabel", { date: formatDate(report.created_at, locale) })}</p>
            {report.resolved_at ? (
              <p>{t("resolvedAtLabel", { date: formatDate(report.resolved_at, locale) })}</p>
            ) : null}
          </div>
        </div>

        {report.reason ? (
          <p className="text-sm leading-6 whitespace-pre-wrap text-foreground">{report.reason}</p>
        ) : (
          <p className="text-sm text-muted-foreground">{t("noReason")}</p>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={togglingHide}
            onClick={() => onToggleHide(!isHidden)}
          >
            {togglingHide ? t("togglingHide") : hideActionLabel}
          </Button>
          {isOpen ? (
            <Button type="button" variant="outline" size="sm" disabled={resolving} onClick={onResolve}>
              {resolving ? t("resolving") : t("resolveAction")}
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
