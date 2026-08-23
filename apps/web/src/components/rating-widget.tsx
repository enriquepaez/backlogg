"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import Image from "next/image";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { StarIcon, StarRating } from "@/components/star-rating";
import { Textarea } from "@/components/ui/textarea";
import { ReportReviewButton } from "@/components/report-review-button";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import { formatDate } from "@/lib/format-date";
import { queryKeys } from "@/lib/queries/query-keys";
import { recomputeAggregate, type RatingAggregate } from "@/lib/ratings-aggregate";

import type { components } from "@backlogg/api-client";

type Rating = components["schemas"]["RatingOut"];
type RatingAuthor = components["schemas"]["RatingAuthorOut"];

/** `GET /api/{type}/{slug}/rating`'s response shape. */
type RatingGetResponse = { authenticated: boolean; rating: Rating | null };

/** Outcome of the `PUT /api/{type}/{slug}/rating` mutation, branched on the response status the same way the original inline `fetch` handler did — kept as a plain return value (not a thrown error) for every *expected* HTTP outcome, so `handleSubmit` can map it to a {@link FormErrorKey} the same way it always did; only a genuine network failure (the `fetch` call itself rejecting) throws, caught by the mutation's caller. */
type SaveRatingResult =
  | { status: "saved"; rating: Rating }
  | { status: "unauthorized" }
  | { status: "validation" }
  | { status: "failed" };

type DeleteRatingResult = { status: "deleted" } | { status: "failed" };

async function fetchViewerRating(type: CatalogType, slug: string): Promise<RatingGetResponse> {
  const response = await fetch(`/api/${type}/${slug}/rating`);
  if (!response.ok) {
    throw new Error(`unexpected status ${response.status}`);
  }
  return (await response.json()) as RatingGetResponse;
}

async function saveRating(
  type: CatalogType,
  slug: string,
  body: { score: number | null; review_text: string | null },
): Promise<SaveRatingResult> {
  const response = await fetch(`/api/${type}/${slug}/rating`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 200) {
    return { status: "saved", rating: (await response.json()) as Rating };
  }
  if (response.status === 401) return { status: "unauthorized" };
  if (response.status === 422) return { status: "validation" };
  return { status: "failed" };
}

async function deleteRatingRequest(type: CatalogType, slug: string): Promise<DeleteRatingResult> {
  const response = await fetch(`/api/${type}/${slug}/rating`, { method: "DELETE" });
  return response.status === 204 ? { status: "deleted" } : { status: "failed" };
}

/** The 5 star positions of the picker — each one splits into two half-point values (`position - 0.5`/`position`), see `StarPicker`. */
const STAR_POSITIONS = [1, 2, 3, 4, 5] as const;
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
 * via the BFF `GET`, through TanStack Query's `useQuery` as of FE-48 — see
 * that feature's `progress/impl_47.md` for why the whole "personal widgets"
 * family moved off raw `useState`+`useEffect`+`fetch`) rather than the
 * page's Server Component passing it down — the item detail page stays a
 * public, ISR-cached Server Component (`src/lib/catalog.ts`'s
 * `ITEM_REVALIDATE_SECONDS`); reading the viewer's session there would force
 * `cookies()` into that render and make the whole page dynamic per request.
 * See `viewer-status-slot.tsx`'s doc comment for the same tension around
 * `viewer_status` (FE-20, still unresolved there).
 *
 * Renders a `"loading"` skeleton for the very first paint (including SSR/the
 * pre-hydration HTML) so this never blocks or alters the page's own
 * server-rendered output — only the client-side fetch after mount decides
 * between the anonymous prompt, the empty-state composer, or the viewer's
 * saved rating. `phase`/`rating` are computed fresh on every render straight
 * from `ratingQuery` (see that computation below) rather than mirrored into
 * their own `useState` via an effect — the local `editing` flag is the only
 * genuinely local piece: it's what lets `phase` land on `"form"` even while
 * an already-loaded `rating` is non-null (`openForm`/`cancelForm` toggle it
 * directly), a distinction that isn't a server data state at all, just a
 * local UI mode no derivation from `ratingQuery` alone could represent.
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
  const queryClient = useQueryClient();

  const ratingQuery = useQuery({
    queryKey: queryKeys.rating.detail(type, slug),
    queryFn: () => fetchViewerRating(type, slug),
  });

  const saveMutation = useMutation({
    mutationFn: (body: { score: number | null; review_text: string | null }) =>
      saveRating(type, slug, body),
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteRatingRequest(type, slug),
  });

  /**
   * Whether the composer is open — the only piece of "what should this
   * widget show" that isn't derived from `ratingQuery` (see `phase`/`rating`
   * below): editing an already-loaded rating is a local UI mode, not a
   * server data state. Defaults to `false`; when there's no saved rating yet
   * `phase` below falls back to `"form"` regardless, so this only matters
   * once a rating exists.
   */
  const [editing, setEditing] = useState(false);
  const [aggregate, setAggregate] = useState<RatingAggregate>({
    ratingInternal: initialRatingInternal,
    ratingCountInternal: initialRatingCountInternal,
  });

  const [score, setScore] = useState<number | null>(null);
  /**
   * Live hover/focus preview for the score picker (post-launch QA fix,
   * FE-44): the half-point value currently under the pointer (or keyboard
   * focus), or `null` when the pointer/focus isn't over any star. `null`
   * falls back to the actually-selected {@link score} — see `displayScore`
   * below, computed once and threaded through every `StarPicker` so all
   * five stars preview the same hypothetical selection in sync (hovering
   * the 4th star's right half fills stars 1-4 solid, not just the one under
   * the cursor). Mirrors Letterboxd/Backloggd's picker convention per
   * explicit QA feedback: without this, a picker whose two half-width click
   * targets are each only a few pixels wide gives the user no visual
   * feedback about where the left/right split actually falls until *after*
   * they've already committed a click — see `StarPicker`'s doc comment for
   * the matching hit-target-size half of this same fix.
   */
  const [hoverScore, setHoverScore] = useState<number | null>(null);
  const [reviewText, setReviewText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [formError, setFormError] = useState<FormErrorKey>(null);

  // `phase`/`rating` are derived straight from `ratingQuery` on every
  // render — not synced into their own state via a `useEffect` (that
  // pattern, tried in an earlier version of this migration, trips
  // `react-hooks/set-state-in-effect`: a `useQuery` result is already
  // reactive state, so mirroring it into a second `useState` is exactly the
  // "you might not need an effect" case that lint rule flags). Mirrors the
  // original inline `load()`'s three branches (still loading, failed, or
  // resolved) — `editing` (declared above) is what supplies the fourth,
  // non-data-driven distinction between `"form"` and `"summary"`.
  let phase: Phase;
  let rating: Rating | null = null;
  if (ratingQuery.isPending) {
    phase = "loading";
  } else if (ratingQuery.isError) {
    phase = "load-error";
  } else if (!ratingQuery.data.authenticated) {
    phase = "anonymous";
  } else {
    rating = ratingQuery.data.rating;
    phase = editing || !rating ? "form" : "summary";
  }

  // Logging-only — no `setState` here, so this doesn't trip
  // `react-hooks/set-state-in-effect` (`phase` above already derives the
  // `"load-error"` UI state on its own, synchronously, every render).
  useEffect(() => {
    if (ratingQuery.isError) {
      console.error("RatingWidget: failed to load the viewer's own rating", ratingQuery.error);
    }
  }, [ratingQuery.isError, ratingQuery.error]);

  function openForm() {
    setScore(rating?.score ?? null);
    setHoverScore(null);
    setReviewText(rating?.review_text ?? "");
    setFormError(null);
    setEditing(true);
  }

  function cancelForm() {
    if (!rating) return;
    setFormError(null);
    setEditing(false);
  }

  /** Selects `value` (a half-point step, e.g. `3` or `3.5`) or clears the score if it's already selected — same toggle-off behavior the single-button-per-star picker had before FE-44 split each star into two half-width click targets. */
  function selectScore(value: number) {
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

    let result: SaveRatingResult;
    try {
      result = await saveMutation.mutateAsync({
        score,
        review_text: trimmedReview.length ? trimmedReview : null,
      });
    } catch {
      setFormError("save");
      setSubmitting(false);
      return;
    }

    if (result.status === "saved") {
      const saved = result.rating;
      setAggregate((current) => recomputeAggregate(current, rating?.score ?? null, saved.score));
      setEditing(false);
      setSubmitting(false);
      // Keeps the query cache in sync with the mutation's result so a later
      // remount (e.g. navigating away and back within `staleTime`) shows the
      // freshly-saved rating without an extra round trip, instead of
      // re-fetching or briefly flashing the pre-save value.
      queryClient.setQueryData(queryKeys.rating.detail(type, slug), {
        authenticated: true,
        rating: saved,
      } satisfies RatingGetResponse);
      toast.success(t("saveSuccess"));
      return;
    }

    if (result.status === "unauthorized") {
      setFormError("unauthorized");
    } else if (result.status === "validation") {
      setFormError("validation");
    } else {
      setFormError("save");
    }
    setSubmitting(false);
  }

  async function handleDelete() {
    if (!rating) return;
    setDeleting(true);

    let result: DeleteRatingResult;
    try {
      result = await deleteMutation.mutateAsync();
    } catch {
      setDeleting(false);
      toast.error(t("deleteError"));
      return;
    }

    if (result.status === "deleted") {
      setAggregate((current) => recomputeAggregate(current, rating.score, null));
      setScore(null);
      setReviewText("");
      setEditing(false);
      setDeleting(false);
      queryClient.setQueryData(queryKeys.rating.detail(type, slug), {
        authenticated: true,
        rating: null,
      } satisfies RatingGetResponse);
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
                  <StarRating score={rating.score} starClassName="size-5" />
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
            <div
              role="group"
              aria-label={t("scoreLabel")}
              className="flex items-center gap-1.5"
              onMouseLeave={() => setHoverScore(null)}
              onBlur={(event) => {
                // Only clear once focus leaves the whole group (not when it
                // just moves from one star's button to the next one inside
                // it) — `relatedTarget` is the element about to receive
                // focus.
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                  setHoverScore(null);
                }
              }}
            >
              {STAR_POSITIONS.map((position) => (
                <StarPicker
                  key={position}
                  position={position}
                  score={score}
                  displayScore={hoverScore ?? score}
                  onSelect={selectScore}
                  onHover={setHoverScore}
                  ariaLabel={(value) => t("starAriaLabel", { value })}
                />
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
 * Mirrors the avatar-or-initials pattern from `user-nav.tsx`'s `UserNav`.
 * Not reusing that component's `initials()`
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
        <Image
          src={user.avatar_url}
          alt=""
          width={24}
          height={24}
          className="size-6 rounded-full object-cover"
        />
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

/**
 * One star position (1-5) of the score picker, split into two half-width,
 * independently focusable/clickable buttons — left selects `position - 0.5`,
 * right selects `position` (FE-44: half-star granularity, mirroring the
 * backend's `user_ratings.score` step of 0.5). Visually renders a single
 * `StarIcon` (the same fill/half/empty logic `StarRating` uses for read-only
 * display, so the picker and the saved-rating summary right above it always
 * agree on what "3.5" looks like) underneath two transparent buttons.
 *
 * Each half is its own real `<button>` — same "one focusable, clickable
 * element per selectable value" shape the previous one-button-per-star
 * picker had, just twice as many of them, so keyboard users can still Tab
 * through and Enter/Space-select every value (1.5, 2, 2.5, ..., 5) without
 * any extra arrow-key handling. The first star (`position === 1`) is the one
 * exception: `position - 0.5` would be `0.5`, below the backend's minimum
 * (`ge=1`, `docs/schema.md`), so its left half is not rendered at all —
 * both halves of the first star select the full value `1`.
 *
 * Post-launch QA fix: two changes on top of the above, neither touched by
 * `starFillAt`/the click-handling logic itself (that part was already
 * pixel-correct — reproduced live against `next dev` in a real Chromium tab
 * via a throwaway Playwright harness rather than trusting jsdom again, given
 * this exact feature already had one bug hidden by a mock once; a 1px sweep
 * across a star's width showed the left/right hit-test boundary lands
 * exactly at the midpoint every time). What real mouse users actually
 * struggle with is aiming at that boundary at all:
 *
 * 1. `size-6` (24px) stars gave each half only a 12px-wide target — under
 *    WCAG 2.5.5's 24px pointer-target guidance even for the *whole* star,
 *    let alone one half of it. Bumped the picker's own stars (only the
 *    interactive picker — `StarRating`'s read-only display elsewhere is
 *    unaffected, no visual regression there) to `size-9` (36px), giving each
 *    half an 18px target.
 * 2. There was no visual feedback at all about where that boundary sits
 *    before committing a click — a real user has no way to self-correct an
 *    almost-right aim. `displayScore` (hover/hover-preview score, computed
 *    in `RatingWidget` from `hoverScore ?? score` and threaded down here)
 *    now drives the rendered `StarIcon` fill independently of the actually
 *    *selected* `score` (still the only thing `aria-pressed` reflects), so
 *    every star lights up live as the pointer (or keyboard focus) moves
 *    across the two buttons, the same live-preview convention
 *    Letterboxd/Backloggd use.
 */
function StarPicker({
  position,
  score,
  displayScore,
  onSelect,
  onHover,
  ariaLabel,
}: {
  position: number;
  /** The actually-selected score — drives `aria-pressed` only. */
  score: number | null;
  /** `hoverScore ?? score` — drives the rendered `StarIcon` fill. */
  displayScore: number | null;
  onSelect: (value: number) => void;
  /** Called on hover/focus of either half with that half's value; `RatingWidget` resets it to `null` when the pointer/focus leaves the whole group. */
  onHover: (value: number) => void;
  ariaLabel: (value: number) => string;
}) {
  const halfValue = position - 0.5;
  const fullValue = position;
  const hasHalf = halfValue >= 1;

  return (
    <span className="relative inline-block size-9">
      <StarIcon
        position={position}
        score={displayScore}
        className="pointer-events-none absolute inset-0 size-9"
      />
      {hasHalf && (
        <button
          type="button"
          aria-pressed={score === halfValue}
          aria-label={ariaLabel(halfValue)}
          onClick={() => onSelect(halfValue)}
          onMouseEnter={() => onHover(halfValue)}
          onFocus={() => onHover(halfValue)}
          className="absolute inset-y-0 left-0 w-1/2 rounded-l focus-visible:outline-2 focus-visible:outline-ring"
        />
      )}
      <button
        type="button"
        aria-pressed={score === fullValue}
        aria-label={ariaLabel(fullValue)}
        onClick={() => onSelect(fullValue)}
        onMouseEnter={() => onHover(fullValue)}
        onFocus={() => onHover(fullValue)}
        className={
          hasHalf
            ? "absolute inset-y-0 right-0 w-1/2 rounded-r focus-visible:outline-2 focus-visible:outline-ring"
            : "absolute inset-0 rounded focus-visible:outline-2 focus-visible:outline-ring"
        }
      />
    </span>
  );
}

