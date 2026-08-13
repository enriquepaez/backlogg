"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import { LIBRARY_STATUSES, type LibraryStatusValue } from "@/lib/library-types";

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
 * comment) and both `setStatusTo`/`remove` optimistically update local state,
 * rolling back and toasting an error (`sonner`, same as `RatingWidget`) on
 * any non-success response or network failure.
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

  const [phase, setPhase] = useState<Phase>("loading");
  const [status, setStatus] = useState<LibraryStatusValue | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch(`/api/${type}/${slug}/library`);
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const data = (await response.json()) as {
          authenticated: boolean;
          status: LibraryStatusValue | null;
        };
        if (cancelled) return;

        if (!data.authenticated) {
          setPhase("anonymous");
          return;
        }
        setStatus(data.status);
        setPhase("ready");
      } catch (error) {
        if (cancelled) return;
        console.error("ViewerStatusSlot: failed to load the viewer's library status", error);
        setPhase("ready");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [type, slug]);

  async function setStatusTo(next: LibraryStatusValue) {
    if (pending) return;
    const previous = status;
    setPending(true);
    setStatus(next);

    let ok = false;
    try {
      const response = await fetch(`/api/${type}/${slug}/library`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: next }),
      });
      ok = response.status === 200;
    } catch {
      ok = false;
    } finally {
      if (!ok) {
        setStatus(previous);
        toast.error(t("error"));
      }
      setPending(false);
    }
  }

  async function remove() {
    if (pending || status === null) return;
    const previous = status;
    setPending(true);
    setStatus(null);

    let ok = false;
    try {
      const response = await fetch(`/api/${type}/${slug}/library`, { method: "DELETE" });
      ok = response.status === 204;
    } catch {
      ok = false;
    } finally {
      if (!ok) {
        setStatus(previous);
        toast.error(t("error"));
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
          <Button
            key={value}
            type="button"
            size="sm"
            variant={status === value ? "default" : "outline"}
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
