"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Star } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ReportReviewButton } from "@/components/report-review-button";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import { formatDate } from "@/lib/format-date";
import { recomputeAggregate, type RatingAggregate } from "@/lib/ratings-aggregate";

import type { components } from "@backlogg/api-client";

type Rating = components["schemas"]["RatingOut"];
type RatingAuthor = components["schemas"]["RatingAuthorOut"];

const SCORES = [1, 2, 3, 4, 5] as const;
const REVIEW_MAX_LENGTH = 10000;

type Phase = "loading" | "anonymous" | "load-error" | "form" | "summary";
type FormErrorKey = "empty" | "unauthorized" | "validation" | "save" | null;

export type RatingWidgetProps = {
  type: CatalogType;
  slug: string;
  /** `MovieOut.rating_internal`/`rating_count_internal` (etc) as rendered by `ItemHero` — the starting point for {@link recomputeAggregate}. */
  initialRatingInternal: number | null;
  initialRatingCountInternal: number;
};

/**
 * Rating + review widget for the item detail page (FE-18): a star picker
 * (1-5) plus an optional review composer, with create/edit/delete against
 * `PUT`/`DELETE /v1/{type}/{slug}/rating` (via the `/api/{type}/{slug}/rating`
 * BFF route) and a "report" action on the viewer's own saved review
 * (`ReportReviewButton`).
 *
 * A Client Component fetching its own initial state client-side (on mount,
 * via the BFF `GET`) rather than the page's Server Component passing it down
 * — the item detail page stays a public, ISR-cached Server Component
 * (`src/lib/catalog.ts`'s `ITEM_REVALIDATE_SECONDS`); reading the viewer's
 * session there would force `cookies()` into that render and make the whole
 * page dynamic per request. See `viewer-status-slot.tsx`'s doc comment for
 * the same tension around `viewer_status` (FE-20, still unresolved there).
 *
 * Renders a `"loading"` skeleton for the very first paint (including SSR/the
 * pre-hydration HTML) so this never blocks or alters the page's own
 * server-rendered output — only the client-side fetch after mount decides
 * between the anonymous prompt, the empty-state composer, or the viewer's
 * saved rating.
 */
export function RatingWidget({
  type,
  slug,
  initialRatingInternal,
  initialRatingCountInternal,
}: RatingWidgetProps) {
  const t = useTranslations("ItemDetail.rating");
  const tErrors = useTranslations("ItemDetail.rating.errors");
  const locale = useLocale();

  const [phase, setPhase] = useState<Phase>("loading");
  const [rating, setRating] = useState<Rating | null>(null);
  const [aggregate, setAggregate] = useState<RatingAggregate>({
    ratingInternal: initialRatingInternal,
    ratingCountInternal: initialRatingCountInternal,
  });

  const [score, setScore] = useState<number | null>(null);
  const [reviewText, setReviewText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [formError, setFormError] = useState<FormErrorKey>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch(`/api/${type}/${slug}/rating`);
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const data = (await response.json()) as { authenticated: boolean; rating: Rating | null };
        if (cancelled) return;

        if (!data.authenticated) {
          setPhase("anonymous");
          return;
        }
        setRating(data.rating);
        setPhase(data.rating ? "summary" : "form");
      } catch (error) {
        if (cancelled) return;
        console.error("RatingWidget: failed to load the viewer's own rating", error);
        setPhase("load-error");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [type, slug]);

  function openForm() {
    setScore(rating?.score ?? null);
    setReviewText(rating?.review_text ?? "");
    setFormError(null);
    setPhase("form");
  }

  function cancelForm() {
    if (!rating) return;
    setFormError(null);
    setPhase("summary");
  }

  function toggleScore(value: number) {
    setScore((current) => (current === value ? null : value));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedReview = reviewText.trim();
    if (score === null && trimmedReview.length === 0) {
      setFormError("empty");
      return;
    }

    setFormError(null);
    setSubmitting(true);

    let response: Response;
    try {
      response = await fetch(`/api/${type}/${slug}/rating`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ score, review_text: trimmedReview.length ? trimmedReview : null }),
      });
    } catch {
      setFormError("save");
      setSubmitting(false);
      return;
    }

    if (response.status === 200) {
      const saved = (await response.json()) as Rating;
      setAggregate((current) => recomputeAggregate(current, rating?.score ?? null, saved.score));
      setRating(saved);
      setPhase("summary");
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

  async function handleDelete() {
    if (!rating) return;
    setDeleting(true);

    let response: Response;
    try {
      response = await fetch(`/api/${type}/${slug}/rating`, { method: "DELETE" });
    } catch {
      setDeleting(false);
      toast.error(t("deleteError"));
      return;
    }

    if (response.status === 204) {
      setAggregate((current) => recomputeAggregate(current, rating.score, null));
      setRating(null);
      setScore(null);
      setReviewText("");
      setPhase("form");
      setDeleting(false);
      toast.success(t("deleteSuccess"));
      return;
    }

    setDeleting(false);
    toast.error(t("deleteError"));
  }

  const aggregateText =
    aggregate.ratingInternal === null
      ? t("noRatings")
      : `${aggregate.ratingInternal.toFixed(1)} (${aggregate.ratingCountInternal})`;

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{t("heading")}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("aggregateLabel", { value: aggregateText })}</p>

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
        ) : phase === "summary" && rating ? (
          <Card>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                <div className="flex flex-col gap-2">
                  <RaterIdentity user={rating.user} />
                  <StarRow score={rating.score} />
                </div>
                <div className="text-xs text-muted-foreground">
                  <p>{t("createdOnLabel", { date: formatDate(rating.created_at, locale) })}</p>
                  {rating.updated_at !== rating.created_at ? (
                    <p>{t("editedOnLabel", { date: formatDate(rating.updated_at, locale) })}</p>
                  ) : null}
                </div>
              </div>
              {rating.review_text ? (
                <p className="max-w-2xl text-sm leading-6 whitespace-pre-wrap text-foreground">
                  {rating.review_text}
                </p>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" variant="outline" size="sm" onClick={openForm}>
                  {t("edit")}
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  disabled={deleting}
                  onClick={handleDelete}
                >
                  {deleting ? t("deleting") : t("delete")}
                </Button>
                <ReportReviewButton ratingId={rating.id} />
              </div>
            </CardContent>
          </Card>
        ) : (
          <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
            <div role="group" aria-label={t("scoreLabel")} className="flex items-center gap-1">
              {SCORES.map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={score === value}
                  aria-label={t("starAriaLabel", { value })}
                  onClick={() => toggleScore(value)}
                  className="rounded p-0.5 focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <Star
                    aria-hidden
                    className={
                      score !== null && value <= score
                        ? "size-6 fill-current text-yellow-500"
                        : "size-6 text-muted-foreground"
                    }
                  />
                </button>
              ))}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="rating-review-text">{t("reviewLabel")}</Label>
              <Textarea
                id="rating-review-text"
                rows={3}
                maxLength={REVIEW_MAX_LENGTH}
                value={reviewText}
                onChange={(event) => setReviewText(event.target.value)}
              />
            </div>

            {formError ? (
              <p role="alert" className="text-sm text-destructive">
                {tErrors(formError)}
              </p>
            ) : null}

            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={submitting} size="sm">
                {submitting ? t("saving") : t("save")}
              </Button>
              {rating ? (
                <Button type="button" variant="outline" size="sm" onClick={cancelForm}>
                  {t("cancel")}
                </Button>
              ) : null}
            </div>
          </form>
        )}
      </div>
    </section>
  );
}

/**
 * Avatar + name of the rating's author (`RatingOut.user`, a `RatingAuthorOut`
 * — `username`/`display_name`/`avatar_url`, snake_case straight from the
 * backend). Today `rating.user` is always the viewer themself (this widget
 * only ever loads/saves the caller's own rating), but the component reads
 * exclusively from the `user` prop rather than any session/auth state, so it
 * makes no assumption either way — the same shape FE-19 will reuse to show
 * *other* users' reviews.
 *
 * Mirrors the avatar-or-initials pattern from `user-nav.tsx`'s `UserNav`
 * (including the same `<img>`-over-`next/image` rationale: avatar hosts
 * aren't in `remotePatterns` yet). Not reusing that component's `initials()`
 * directly — it isn't exported, and its `NavUser` shape is camelCase
 * (`displayName`/`avatarUrl`) while `RatingAuthorOut` is snake_case, so
 * reusing it would mean building an adapter object just to call a 3-line
 * helper; duplicating those 3 lines here is simpler than forcing a shared
 * abstraction for a single extra call site.
 */
function RaterIdentity({ user }: { user: RatingAuthor }) {
  const name = user.display_name ?? user.username;

  return (
    <div className="flex items-center gap-2">
      {user.avatar_url ? (
        // Avatar hosts aren't configured in `next/image`'s remotePatterns
        // yet (catalog-image scope, later features); a plain <img> avoids
        // that dependency for now.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={user.avatar_url} alt="" className="size-6 rounded-full object-cover" />
      ) : (
        <span
          aria-hidden="true"
          className="flex size-6 items-center justify-center rounded-full bg-muted text-xs"
        >
          {raterInitials(user)}
        </span>
      )}
      <span className="text-sm font-medium">{name}</span>
    </div>
  );
}

function raterInitials(user: Pick<RatingAuthor, "username" | "display_name">): string {
  const source = user.display_name ?? user.username;
  return source.slice(0, 2).toUpperCase();
}

function StarRow({ score }: { score: number | null }) {
  return (
    <div className="flex items-center gap-1">
      {SCORES.map((value) => (
        <Star
          key={value}
          aria-hidden
          className={
            score !== null && value <= score
              ? "size-5 fill-current text-yellow-500"
              : "size-5 text-muted-foreground"
          }
        />
      ))}
    </div>
  );
}

