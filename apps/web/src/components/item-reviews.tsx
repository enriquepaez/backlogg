"use client";

import { useEffect, useState } from "react";
import { Heart, Star } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Link } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import { formatDate } from "@/lib/format-date";

import type { components } from "@backlogg/api-client";

type Rating = components["schemas"]["RatingOut"];
type RatingAuthor = components["schemas"]["RatingAuthorOut"];

const SCORES = [1, 2, 3, 4, 5] as const;
/** Page size for the reviews listing — mirrors `DEFAULT_LIMIT` in the BFF route (`app/api/[type]/[slug]/ratings/route.ts`). */
const PAGE_LIMIT = 10;

type Phase = "loading" | "error" | "ready";

type ReviewsResponse = {
  authenticated: boolean;
  items: Rating[];
  total: number;
  page: number;
  limit: number;
};

/**
 * Per-review client-side like state, keyed by `RatingOut.id`. `pending`
 * guards against double-submit and the revert race described in
 * `toggleLike`'s doc comment — mirrors `submitting`/`deleting` in
 * `rating-widget.tsx` (FE-18), just scoped per review instead of a single
 * widget-wide flag.
 */
type LikeState = Record<number, { liked: boolean; count: number; pending: boolean }>;

export type ItemReviewsProps = {
  type: CatalogType;
  slug: string;
};

/**
 * Paginated reviews listing for the item detail page (FE-19): every review
 * for the item with its author, score, text and like count, plus like/unlike
 * on each one. Companion to `RatingWidget` (FE-18, the viewer's own
 * rating/review) — both mount on the same item detail page
 * (`src/app/[locale]/[type]/[slug]/page.tsx`), this one shows everyone
 * else's.
 *
 * A Client Component fetching its own data client-side (on mount and on page
 * change, via the BFF `GET /api/{type}/{slug}/ratings`) for the same reason
 * `RatingWidget` does (see its own doc comment): the item detail page stays
 * a public, ISR-cached Server Component, and pagination here is driven by
 * local `page` state rather than the URL, so it never has to make that page
 * dynamic per request.
 *
 * `RatingOut.liked_by_viewer` (resolved server-side for the authenticated
 * caller, always `false` for an anonymous one — see `docs/api.md`) seeds
 * each review's initial `liked` state, so the heart reflects the viewer's
 * real prior like on load instead of always starting unliked. Previously
 * every review started "not liked by me" regardless of the viewer's true
 * prior like, since `RatingOut` didn't expose that — see
 * `progress/current.md`'s "Refinamiento fuera de backlog" (ronda 2) for the
 * QA report and root-cause diagnosis.
 */
export function ItemReviews({ type, slug }: ItemReviewsProps) {
  const t = useTranslations("ItemDetail.reviews");
  const locale = useLocale();

  const [phase, setPhase] = useState<Phase>("loading");
  const [items, setItems] = useState<Rating[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [authenticated, setAuthenticated] = useState(false);
  const [likeState, setLikeState] = useState<LikeState>({});

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setPhase("loading");
      try {
        const response = await fetch(
          `/api/${type}/${slug}/ratings?page=${page}&limit=${PAGE_LIMIT}`,
        );
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const data = (await response.json()) as ReviewsResponse;
        if (cancelled) return;

        setAuthenticated(data.authenticated);
        setItems(data.items);
        setTotal(data.total);
        setLikeState(
          Object.fromEntries(
            data.items.map((item) => [
              item.id,
              { liked: item.liked_by_viewer, count: item.like_count, pending: false },
            ]),
          ),
        );
        setPhase("ready");
      } catch (error) {
        if (cancelled) return;
        console.error("ItemReviews: failed to load reviews", error);
        setPhase("error");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [type, slug, page]);

  /**
   * Toggles like/unlike for one review. Guarded per `ratingId` by
   * `likeState[ratingId].pending` (see the `LikeState` doc comment) to close
   * two gaps flagged in review (`progress/review_20.md`, "Cambios
   * requeridos" #1):
   *
   * - **Double-submit**: a no-op early return while a request for this
   *   `ratingId` is already in flight, same intent as `submitting`/`deleting`
   *   disabling the button in `rating-widget.tsx`.
   * - **Revert race**: without this guard, two fast clicks each capture their
   *   own `previous` by closure; if their responses resolve out of order, a
   *   late revert from the first request can stomp the state a more recent
   *   click already applied. Blocking new requests for the same `ratingId`
   *   until the in-flight one settles removes that window entirely — no
   *   `AbortController`/timestamp sequencing needed.
   *
   * `pending` is always cleared in the single `finally`, covering all three
   * outcomes (204 success, non-204 status, network exception) so the control
   * never gets stuck disabled.
   */
  async function toggleLike(ratingId: number) {
    const previous = likeState[ratingId];
    if (!previous || previous.pending) return;

    const optimistic = {
      liked: !previous.liked,
      count: previous.count + (previous.liked ? -1 : 1),
      pending: true,
    };
    setLikeState((state) => ({ ...state, [ratingId]: optimistic }));

    let failed = false;
    try {
      const response = await fetch(`/api/reviews/${ratingId}/like`, {
        method: optimistic.liked ? "POST" : "DELETE",
      });
      failed = response.status !== 204;
    } catch {
      failed = true;
    } finally {
      setLikeState((state) => ({
        ...state,
        [ratingId]: failed ? { ...previous, pending: false } : { ...optimistic, pending: false },
      }));
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_LIMIT));

  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{t("heading")}</h2>

      <div className="mt-4 flex flex-col gap-4">
        {phase === "loading" ? (
          <p className="text-sm text-muted-foreground">{t("loading")}</p>
        ) : phase === "error" ? (
          <p role="alert" className="text-sm text-destructive">
            {t("loadError")}
          </p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <>
            {items.map((review) => (
              <ReviewCard
                key={review.id}
                review={review}
                locale={locale}
                authenticated={authenticated}
                liked={likeState[review.id]?.liked ?? false}
                likeCount={likeState[review.id]?.count ?? review.like_count}
                pending={likeState[review.id]?.pending ?? false}
                onToggleLike={() => toggleLike(review.id)}
                t={t}
              />
            ))}

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
      </div>
    </section>
  );
}

type ReviewsTranslator = ReturnType<typeof useTranslations<"ItemDetail.reviews">>;

/**
 * A single review: author (linked to their public profile), score, text and
 * the like control. `authenticated` gates the like control the same way
 * `RatingWidget`'s anonymous state gates rating — see FE-18's
 * `anonymousPrompt`/`anonymousLoginLink` pattern: an anonymous viewer gets a
 * plain link to `/login` in place of the interactive button, rather than a
 * disabled control with no way forward.
 */
function ReviewCard({
  review,
  locale,
  authenticated,
  liked,
  likeCount,
  pending,
  onToggleLike,
  t,
}: {
  review: Rating;
  locale: string;
  authenticated: boolean;
  liked: boolean;
  likeCount: number;
  pending: boolean;
  onToggleLike: () => void;
  t: ReviewsTranslator;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <div className="flex flex-col gap-2">
            <ReviewAuthor user={review.user} />
            <ReviewStars score={review.score} />
          </div>
          <p className="text-xs text-muted-foreground">
            {t("dateLabel", { date: formatDate(review.created_at, locale) })}
          </p>
        </div>

        {review.review_text ? (
          <p className="max-w-2xl text-sm leading-6 whitespace-pre-wrap text-foreground">
            {review.review_text}
          </p>
        ) : null}

        {authenticated ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-pressed={liked}
            aria-label={liked ? t("unlikeAriaLabel") : t("likeAriaLabel")}
            disabled={pending}
            onClick={onToggleLike}
            className="w-fit gap-1.5"
          >
            <Heart aria-hidden className={liked ? "size-4 fill-current text-red-500" : "size-4"} />
            {t("likeCount", { count: likeCount })}
          </Button>
        ) : (
          <Link
            href="/login"
            aria-label={t("likeAriaLabel")}
            className="flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <Heart aria-hidden className="size-4" />
            {t("likeCount", { count: likeCount })}
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Avatar + name of a review's author, linked to their public profile
 * (`/u/{username}`, FE-21).
 *
 * Deliberately not reusing `RaterIdentity` from `rating-widget.tsx`: that
 * one renders the viewer's own identity with no link (FE-18's scope never
 * surfaced anyone else's review), while this one must link out — same
 * "duplicate a few lines rather than force a shared abstraction for a
 * second call site with different requirements" rationale `RaterIdentity`'s
 * own doc comment already applies to `user-nav.tsx`'s `initials()`.
 */
function ReviewAuthor({ user }: { user: RatingAuthor }) {
  const name = user.display_name ?? user.username;

  return (
    <Link href={`/u/${user.username}`} className="flex w-fit items-center gap-2">
      {user.avatar_url ? (
        // Avatar hosts aren't configured in next/image's remotePatterns yet
        // (catalog-image scope, later features) — same rationale as
        // `RaterIdentity` in `rating-widget.tsx`.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={user.avatar_url} alt="" className="size-6 rounded-full object-cover" />
      ) : (
        <span
          aria-hidden="true"
          className="flex size-6 items-center justify-center rounded-full bg-muted text-xs"
        >
          {name.slice(0, 2).toUpperCase()}
        </span>
      )}
      <span className="text-sm font-medium hover:underline">{name}</span>
    </Link>
  );
}

function ReviewStars({ score }: { score: number | null }) {
  return (
    <div className="flex items-center gap-1">
      {SCORES.map((value) => (
        <Star
          key={value}
          aria-hidden
          className={
            score !== null && value <= score
              ? "size-4 fill-current text-yellow-500"
              : "size-4 text-muted-foreground"
          }
        />
      ))}
    </div>
  );
}
