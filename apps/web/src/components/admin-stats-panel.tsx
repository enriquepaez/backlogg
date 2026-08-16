"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/format-date";

type ContentStats = { count: number; last_synced_at: string | null };
type AdminStats = {
  movies: ContentStats;
  series: ContentStats;
  books: ContentStats;
  games: ContentStats;
};

const STAT_TYPES = ["movies", "series", "books", "games"] as const;

type PanelState =
  | { status: "loading" }
  | { status: "loaded"; stats: AdminStats }
  | { status: "error"; reason: "unauthorized" | "not_configured" | "unknown" };

/**
 * Client Component (FE-28): fetches `GET /api/admin/stats` on mount — the
 * only caller of that Route Handler, which is the only place that ever sees
 * (server-side) the real `X-API-Key`. This component, like the browser, never
 * has access to it: it only ever sees the JSON stats body or a generic error
 * reason (`unauthorized` / `not_configured` / `unknown`), same shape as
 * `NotificationBell`'s `fetch("/api/notifications/...")` pattern (a Client
 * Component can't import `server-only` libs directly).
 *
 * `unauthorized`/`not_configured` map 1:1 to the backend's own 401/503
 * semantics for `/v1/admin/*` (`backlogg/admin/auth.py`, `docs/api.md`) as
 * relayed by the Route Handler (`../app/api/admin/stats/route.ts`) — shown
 * as distinct, actionable messages rather than a single generic error, since
 * they mean different things to whoever is looking at this page (wrong key
 * vs. nothing configured yet).
 */
export function AdminStatsPanel() {
  const t = useTranslations("Admin");
  const locale = useLocale();
  const [state, setState] = useState<PanelState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch("/api/admin/stats");
        if (cancelled) return;

        if (response.status === 200) {
          const stats = (await response.json()) as AdminStats;
          setState({ status: "loaded", stats });
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
  }, []);

  if (state.status === "loading") {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t("loading")}
      </p>
    );
  }

  if (state.status === "error") {
    return (
      <p role="alert" className="text-sm text-destructive">
        {t(`errors.${state.reason}`)}
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {STAT_TYPES.map((type) => {
        const stat = state.stats[type];
        return (
          <Card key={type}>
            <CardHeader>
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t(`types.${type}`)}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold tracking-tight">{stat.count}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {stat.last_synced_at
                  ? t("lastSyncedAt", { date: formatDate(stat.last_synced_at, locale) })
                  : t("lastSyncedNever")}
              </p>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
