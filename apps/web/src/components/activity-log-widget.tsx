"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Link } from "@/i18n/navigation";
import type { MyLogEntry } from "@/lib/activity-log";
import type { CatalogType } from "@/lib/catalog-types";
import { formatDate } from "@/lib/format-date";

const NOTE_MAX_LENGTH = 10000;

type Phase = "loading" | "anonymous" | "load-error" | "ready";
type FormErrorKey = "unauthorized" | "validation" | "save" | null;

export type ActivityLogWidgetProps = {
  type: CatalogType;
  slug: string;
};

/** Today's date as `YYYY-MM-DD`, in the browser's local timezone — the create form's default `logged_on` and its `max` bound (a future date is a 422, `docs/api.md`). */
function todayIso(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Inserts `entry` into `entries`, keeping the same `logged_on desc, id desc` order the backend uses (`docs/api.md`). */
function insertSorted(entries: MyLogEntry[], entry: MyLogEntry): MyLogEntry[] {
  const next = [...entries, entry];
  next.sort((a, b) => (a.logged_on !== b.logged_on ? (a.logged_on < b.logged_on ? 1 : -1) : b.id - a.id));
  return next;
}

/**
 * Activity log widget for the item detail page (FE-41, backend feature 52):
 * a control to log a new dated session (rewatch/replay/reread) plus the
 * viewer's own log history for this item, with per-entry delete.
 *
 * Independent from `RatingWidget` (FE-18/19) — logging a session has no
 * `score`/`review_text` of its own and never touches the rating/review row;
 * both widgets mount side by side on the item detail page
 * (`src/app/[locale]/[type]/[slug]/page.tsx`) and neither reads the other's
 * state.
 *
 * A Client Component fetching its own initial state client-side (on mount,
 * via the BFF `GET /api/{type}/{slug}/log`), same reasoning as `RatingWidget`
 * (see its own doc comment): the item detail page stays a public, ISR-cached
 * Server Component, so nothing here can read the viewer's session during
 * that render.
 *
 * The GET route's `mine` field (not its `items`/`total`/`page`/`limit`,
 * which mirror the public item-scoped listing) is what this widget renders
 * as history — see that route's doc comment for how "the caller's own logs
 * for this item" is derived and its known scan-limit caveat.
 */
export function ActivityLogWidget({ type, slug }: ActivityLogWidgetProps) {
  const t = useTranslations("ItemDetail.activityLog");
  const tErrors = useTranslations("ItemDetail.activityLog.errors");
  const locale = useLocale();

  const [phase, setPhase] = useState<Phase>("loading");
  const [entries, setEntries] = useState<MyLogEntry[]>([]);

  const [loggedOn, setLoggedOn] = useState(todayIso());
  const [rewatch, setRewatch] = useState(false);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<FormErrorKey>(null);
  const [deletingIds, setDeletingIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch(`/api/${type}/${slug}/log`);
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const data = (await response.json()) as { authenticated: boolean; mine: MyLogEntry[] };
        if (cancelled) return;

        if (!data.authenticated) {
          setPhase("anonymous");
          return;
        }
        setEntries(data.mine);
        setPhase("ready");
      } catch (error) {
        if (cancelled) return;
        console.error("ActivityLogWidget: failed to load the viewer's own log history", error);
        setPhase("load-error");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [type, slug]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setFormError(null);
    setSubmitting(true);

    const trimmedNote = note.trim();

    let response: Response;
    try {
      response = await fetch(`/api/${type}/${slug}/log`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          logged_on: loggedOn || null,
          rewatch,
          note: trimmedNote.length ? trimmedNote : null,
        }),
      });
    } catch {
      setFormError("save");
      setSubmitting(false);
      return;
    }

    if (response.status === 201) {
      const saved = (await response.json()) as { id: number; logged_on: string; rewatch: boolean; note: string | null };
      setEntries((current) =>
        insertSorted(current, { id: saved.id, logged_on: saved.logged_on, rewatch: saved.rewatch, note: saved.note }),
      );
      setLoggedOn(todayIso());
      setRewatch(false);
      setNote("");
      setSubmitting(false);
      toast.success(t("saveSuccess"));
      return;
    }

    if (response.status === 401) {
      setFormError("unauthorized");
    } else if (response.status === 422) {
      setFormError("validation");
    } else {
      setFormError("save");
    }
    setSubmitting(false);
  }

  async function handleDelete(id: number) {
    if (deletingIds.has(id)) return;
    setDeletingIds((current) => new Set(current).add(id));

    let response: Response;
    try {
      response = await fetch(`/api/log/${id}`, { method: "DELETE" });
    } catch {
      setDeletingIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      toast.error(t("deleteError"));
      return;
    }

    setDeletingIds((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });

    if (response.status === 204) {
      setEntries((current) => current.filter((entry) => entry.id !== id));
      toast.success(t("deleteSuccess"));
      return;
    }

    toast.error(t("deleteError"));
  }

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{t("heading")}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("description")}</p>

      <div className="mt-4">
        {phase === "loading" ? (
          <p className="text-sm text-muted-foreground">{t("loading")}</p>
        ) : phase === "load-error" ? (
          <p role="alert" className="text-sm text-destructive">
            {t("loadError")}
          </p>
        ) : phase === "anonymous" ? (
          <p className="text-sm text-muted-foreground">
            {t("anonymousPrompt")}{" "}
            <Link href="/login" className="font-medium text-foreground underline underline-offset-4">
              {t("anonymousLoginLink")}
            </Link>
          </p>
        ) : (
          <div className="flex flex-col gap-6">
            <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
              <div className="flex flex-wrap items-end gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="log-date">{t("dateLabel")}</Label>
                  <Input
                    id="log-date"
                    type="date"
                    max={todayIso()}
                    value={loggedOn}
                    onChange={(event) => setLoggedOn(event.target.value)}
                    className="w-auto"
                  />
                </div>
                <label className="flex items-center gap-1.5 pb-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={rewatch}
                    onChange={(event) => setRewatch(event.target.checked)}
                    className="size-4 rounded border-input"
                  />
                  {t("rewatchLabel")}
                </label>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="log-note">{t("noteLabel")}</Label>
                <Textarea
                  id="log-note"
                  rows={2}
                  maxLength={NOTE_MAX_LENGTH}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </div>

              {formError ? (
                <p role="alert" className="text-sm text-destructive">
                  {tErrors(formError)}
                </p>
              ) : null}

              <div>
                <Button type="submit" disabled={submitting} size="sm">
                  {submitting ? t("saving") : t("addEntry")}
                </Button>
              </div>
            </form>

            <div className="flex flex-col gap-3">
              <h3 className="text-sm font-medium text-muted-foreground">{t("historyHeading")}</h3>
              {entries.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("historyEmpty")}</p>
              ) : (
                entries.map((entry) => (
                  <LogEntryCard
                    key={entry.id}
                    entry={entry}
                    locale={locale}
                    deleting={deletingIds.has(entry.id)}
                    onDelete={() => handleDelete(entry.id)}
                    t={t}
                  />
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

type ActivityLogTranslator = ReturnType<typeof useTranslations<"ItemDetail.activityLog">>;

function LogEntryCard({
  entry,
  locale,
  deleting,
  onDelete,
  t,
}: {
  entry: MyLogEntry;
  locale: string;
  deleting: boolean;
  onDelete: () => void;
  t: ActivityLogTranslator;
}) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium">{formatDate(entry.logged_on, locale)}</p>
          <p className="text-xs text-muted-foreground">{entry.rewatch ? t("rewatchYes") : t("rewatchNo")}</p>
          {entry.note ? (
            <p className="max-w-2xl text-sm leading-6 whitespace-pre-wrap text-foreground">{entry.note}</p>
          ) : null}
        </div>
        <Button type="button" variant="destructive" size="sm" disabled={deleting} onClick={onDelete}>
          {deleting ? t("deleting") : t("delete")}
        </Button>
      </CardContent>
    </Card>
  );
}
