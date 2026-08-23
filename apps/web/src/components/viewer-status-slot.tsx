"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import {
  LIBRARY_STATUSES,
  STATUS_COLOR_CLASSES_IMPORTANT,
  type LibraryStatusValue,
} from "@/lib/library-types";
import { queryKeys } from "@/lib/queries/query-keys";
import { cn } from "@/lib/utils";

/** `GET /api/{type}/{slug}/library`'s response shape. */
type LibraryStatusGetResponse = { authenticated: boolean; status: LibraryStatusValue | null };

/** Mutation outcomes only ever distinguish success/failure — the caller (`setStatusTo`/`remove`) only ever branches on that, same as the original inline `fetch` calls, which read nothing but `response.status` off a successful/failed PUT/DELETE. A thrown error (network failure) is treated identically to a `"failed"` result by both callers' `try`/`catch`. */
type LibraryMutationResult = { status: "ok" } | { status: "failed" };

async function fetchViewerLibraryStatus(
  type: CatalogType,
  slug: string,
): Promise<LibraryStatusGetResponse> {
  const response = await fetch(`/api/${type}/${slug}/library`);
  if (!response.ok) {
    throw new Error(`unexpected status ${response.status}`);
  }
  return (await response.json()) as LibraryStatusGetResponse;
}

async function putViewerLibraryStatus(
  type: CatalogType,
  slug: string,
  status: LibraryStatusValue,
): Promise<LibraryMutationResult> {
  const response = await fetch(`/api/${type}/${slug}/library`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  return response.status === 200 ? { status: "ok" } : { status: "failed" };
}

async function deleteViewerLibraryStatus(
  type: CatalogType,
  slug: string,
): Promise<LibraryMutationResult> {
  const response = await fetch(`/api/${type}/${slug}/library`, { method: "DELETE" });
  return response.status === 204 ? { status: "ok" } : { status: "failed" };
}

export type ViewerStatusSlotProps = {
  /**
   * `MovieOut.viewer_status` / `SeriesOut.viewer_status` / etc, as threaded
   * down from `ItemHero`'s own prop of the same name. Unused today — see the
   * doc comment below — kept so `ItemHero` doesn't need to change its own
   * prop just because this component now fetches its own state.
   */
  status: string | null | undefined;
  type: CatalogType;
  slug: string;
};

type Phase = "loading" | "anonymous" | "ready";

/**
 * "Your status" control for the item detail page (FE-20): add/change/remove
 * the caller's own backlog status (`want`/`in_progress`/`completed`/
 * `dropped`) via `PUT`/`DELETE /v1/{type}/{slug}/library`.
 *
 * A Client Component fetching its own initial state client-side (on mount,
 * via the BFF `GET /api/{type}/{slug}/library`) rather than reading the
 * `status` prop the item detail page passes down — same reasoning as
 * `RatingWidget` (`rating-widget.tsx`, FE-18): the item detail page stays a
 * public, ISR-cached Server Component whose own fetch never sends
 * cookies/Authorization, so `item.viewer_status` (and therefore this
 * component's `status` prop) is always `null` in practice. The `status` prop
 * is kept only so `ItemHero` doesn't need an unrelated change, and is
 * otherwise ignored in favor of this component's own `GET`.
 *
 * Renders a `"loading"` placeholder for the very first paint (including
 * SSR/pre-hydration HTML) so this never blocks or alters the page's own
 * server-rendered output.
 *
 * `pending` guards every mutation against double-submit (same fix FE-19
 * applied to review likes, see `item-reviews.tsx`'s `toggleLike` doc
 * comment). Kept as its own plain `useState` (FE-48) rather than reading
 * `setStatusMutation.isPending`/`deleteMutation.isPending` directly: those
 * two flags are set by TanStack Query's own (microtask-batched)
 * notifications, whereas `pending` is set synchronously at the very top of
 * `setStatusTo`/`remove`, before either mutation starts — the same guarantee
 * the "ignores a second click while a mutation is still pending" test
 * (`viewer-status-slot.test.tsx`) depends on: two synchronous clicks with no
 * `await` in between must only ever trigger one `PUT`.
 *
 * Unlike `pending`, `status` itself is *not* separate local state (FE-48;
 * an earlier version of this migration tried that, syncing it from
 * `statusQuery` via a `useEffect` — that pattern trips
 * `react-hooks/set-state-in-effect`, since a `useQuery` result is already
 * reactive state). `status`/`phase` below are derived straight from
 * `statusQuery` on every render, and the "optimistic update, roll back and
 * toast an error on any non-success response or network failure" behavior
 * lives entirely in `queryClient.setQueryData` calls inside `setStatusTo`/
 * `remove` themselves (a plain synchronous write at the very top, matching
 * `next`, then either left in place on success or restored to the
 * pre-mutation snapshot in the `finally` block on failure) — the standard
 * TanStack Query "optimistic update via the cache" shape, rather than a
 * parallel piece of local state the query could drift out of sync with.
 *
 * FE-48: on a successful `setStatusTo`/`remove`, also invalidates
 * `queryKeys.library.counts.all` — the public per-status counts shown on
 * `/u/{username}` (`library-status-counts.tsx`). The viewer's own library
 * status and their profile's aggregate counts live in entirely separate
 * routes/component trees with no shared props, so this shared, structured
 * query key (`@/lib/queries/query-keys.ts`) is the only thing connecting
 * them — see that module's doc comment for the full rationale, including why
 * this invalidates the whole `counts` family rather than a single username.
 *
 * Known limitation: a failed *initial* load (network error, unexpected
 * status) is swallowed into `"ready"` with `status: null` rather than a
 * distinct error phase — unlike `RatingWidget`'s `"load-error"` phase. This
 * looks like "no library entry yet" instead of "couldn't check", but the
 * control still works from there (any status the viewer picks upserts
 * correctly); a genuinely broken backend would fail the mutation too, which
 * *does* surface an error toast. Acceptable trade-off for FE-20's scope —
 * flagged here for a future pass if it proves confusing in practice.
 */
export function ViewerStatusSlot({ type, slug }: ViewerStatusSlotProps) {
  const t = useTranslations("ItemDetail.library");
  const queryClient = useQueryClient();
  const statusKey = queryKeys.library.status(type, slug);

  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: () => fetchViewerLibraryStatus(type, slug),
  });
  const setStatusMutation = useMutation({
    mutationFn: (next: LibraryStatusValue) => putViewerLibraryStatus(type, slug, next),
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteViewerLibraryStatus(type, slug),
  });

  const [pending, setPending] = useState(false);

  // See this component's own doc comment for why `phase`/`status` are
  // derived here instead of synced into their own state via an effect. The
  // `isError` branch keeps the documented "known limitation": it degrades to
  // `"ready"` with `status: null`, not a distinct error phase.
  let phase: Phase;
  let status: LibraryStatusValue | null = null;
  if (statusQuery.isPending) {
    phase = "loading";
  } else if (statusQuery.isError) {
    phase = "ready";
  } else if (!statusQuery.data.authenticated) {
    phase = "anonymous";
  } else {
    phase = "ready";
    status = statusQuery.data.status;
  }

  // Logging-only — no `setState`, so this doesn't trip
  // `react-hooks/set-state-in-effect` (`phase` above already derives the
  // degraded `"ready"` state on its own, synchronously, every render).
  useEffect(() => {
    if (statusQuery.isError) {
      console.error("ViewerStatusSlot: failed to load the viewer's library status", statusQuery.error);
    }
  }, [statusQuery.isError, statusQuery.error]);

  async function setStatusTo(next: LibraryStatusValue) {
    if (pending) return;
    const previous = queryClient.getQueryData<LibraryStatusGetResponse>(statusKey);
    setPending(true);
    queryClient.setQueryData(statusKey, {
      authenticated: true,
      status: next,
    } satisfies LibraryStatusGetResponse);

    let ok = false;
    try {
      const result = await setStatusMutation.mutateAsync(next);
      ok = result.status === "ok";
    } catch {
      ok = false;
    } finally {
      if (!ok) {
        queryClient.setQueryData(statusKey, previous);
        toast.error(t("error"));
      } else {
        queryClient.invalidateQueries({ queryKey: queryKeys.library.counts.all });
      }
      setPending(false);
    }
  }

  async function remove() {
    if (pending || status === null) return;
    const previous = queryClient.getQueryData<LibraryStatusGetResponse>(statusKey);
    setPending(true);
    queryClient.setQueryData(statusKey, {
      authenticated: true,
      status: null,
    } satisfies LibraryStatusGetResponse);

    let ok = false;
    try {
      const result = await deleteMutation.mutateAsync();
      ok = result.status === "ok";
    } catch {
      ok = false;
    } finally {
      if (!ok) {
        queryClient.setQueryData(statusKey, previous);
        toast.error(t("error"));
      } else {
        queryClient.invalidateQueries({ queryKey: queryKeys.library.counts.all });
      }
      setPending(false);
    }
  }

  if (phase === "loading") {
    return <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  }

  if (phase === "anonymous") {
    return (
      <p className="text-sm text-muted-foreground">
        {t("anonymousPrompt")}{" "}
        <Link href="/login" className="font-medium text-foreground underline underline-offset-4">
          {t("anonymousLoginLink")}
        </Link>
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium text-muted-foreground">{t("heading")}</span>
      <div role="group" aria-label={t("heading")} className="flex flex-wrap gap-2">
        {LIBRARY_STATUSES.map((value) => (
          // `STATUS_COLOR_CLASSES_IMPORTANT` (not the plain
          // `STATUS_COLOR_CLASSES` used by `CatalogCard`'s badge and
          // `StatusTabs` in `library/page.tsx`) — this button carries
          // `variant="outline"`, whose `dark:*` classes otherwise win the
          // cascade over the status color in dark theme. See the doc
          // comment on `STATUS_COLOR_CLASSES_IMPORTANT` (FE-37 bugfix).
          <Button
            key={value}
            type="button"
            size="sm"
            variant="outline"
            className={cn(
              status === value && `!border-transparent ${STATUS_COLOR_CLASSES_IMPORTANT[value]}`,
            )}
            aria-pressed={status === value}
            disabled={pending}
            onClick={() => setStatusTo(value)}
          >
            {t(`status.${value}`)}
          </Button>
        ))}
        {status !== null ? (
          <Button type="button" size="sm" variant="destructive" disabled={pending} onClick={remove}>
            {t("remove")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
