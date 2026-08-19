import { Star } from "lucide-react";

import { cn } from "@/lib/utils";

const STAR_POSITIONS = [1, 2, 3, 4, 5] as const;

export type StarRatingProps = {
  /** 1-5 in half-star steps (1.0, 1.5, ..., 5.0), or `null` for "no rating yet" (all five stars empty). */
  score: number | null;
  /** Size classes applied to each star icon (e.g. Tailwind's `size-4`/`size-5`). Defaults to `size-4`, the size used by most call sites. */
  starClassName?: string;
};

/**
 * Read-only 5-star display shared by every place that renders a saved
 * `user_ratings.score`: `rating-widget.tsx`'s own summary (previously a
 * private `StarRow`), `item-reviews.tsx`'s `ReviewStars`,
 * `user-review-card.tsx`'s (exported, tested) `ReviewStars` and
 * `feed-entry-list.tsx`'s `FeedEntryStars`.
 *
 * Extracted for FE-44 (half-star granularity, backend feature
 * `rating_score_granularity`): the half-star fill itself (`StarIcon`'s
 * `"half"` case — a filled star clipped to its left 50%, stacked over a
 * plain outline star) is a few fiddly lines that are easy to get subtly
 * wrong, and every one of these four call sites needs the *exact same*
 * rendering — worth breaking from this codebase's usual "duplicate rather
 * than force a shared abstraction" call (see `ReviewAuthor`'s doc comment in
 * `item-reviews.tsx`) specifically for this one visual primitive. Each call
 * site's surrounding card (author, date, likes, badges, ...) stays separate,
 * same as before — only the star row itself moved here.
 */
export function StarRating({ score, starClassName = "size-4" }: StarRatingProps) {
  return (
    <div className="flex items-center gap-1">
      {STAR_POSITIONS.map((position) => (
        <StarIcon key={position} position={position} score={score} className={starClassName} />
      ))}
    </div>
  );
}

export type StarFill = "empty" | "half" | "full";

/**
 * Whether the star at `position` (1-5) should render empty, half or fully
 * filled for a given `score`. Shared by `StarRating` (read-only display) and
 * `rating-widget.tsx`'s interactive picker (whose visual layer must match
 * this exactly, so a selected `X.5` looks identical whether it came from the
 * picker or from `StarRating` rendering the saved rating right after).
 */
export function starFillAt(position: number, score: number | null): StarFill {
  if (score === null) return "empty";
  const floorScore = Math.floor(score);
  if (position <= floorScore) return "full";
  if (position === floorScore + 1 && score - floorScore >= 0.5) return "half";
  return "empty";
}

/**
 * A single star icon at `position`, filled/half/empty per `starFillAt`.
 * Exported (not just used internally by `StarRating`) so
 * `rating-widget.tsx`'s interactive picker can reuse the identical half-star
 * visual behind its click targets instead of a second, slightly-different
 * copy of the clip trick.
 */
export function StarIcon({
  position,
  score,
  className = "size-4",
}: {
  position: number;
  score: number | null;
  className?: string;
}) {
  const fill = starFillAt(position, score);

  if (fill === "full") {
    return <Star aria-hidden className={cn(className, "fill-current text-yellow-500")} />;
  }
  if (fill === "half") {
    return <HalfStar className={className} />;
  }
  return <Star aria-hidden className={cn(className, "text-muted-foreground")} />;
}

/**
 * A half-filled star: a plain outline star behind a second, fully filled
 * star clipped to its left 50% (`w-1/2 overflow-hidden`), stacked on top via
 * `absolute inset-0` inside a `relative` wrapper sized to match `className`.
 *
 * Bugfix (post-launch QA, FE-44 follow-up): both inner `Star`s must be given
 * the exact same explicit size as the wrapper (`className`, e.g. `size-9`) —
 * *not* `size-full`. `size-full` resolves to `width:100%;height:100%` of the
 * icon's *immediate* containing block; for the outline star that's the
 * square `className`-sized wrapper, so `size-full` happens to look right
 * there, but the filled star's containing block is the *clip* span, which is
 * only half as wide (`w-1/2`) yet full height. Sized at `size-full`, the
 * inner `<svg>`'s own box becomes that same non-square half-width/full-height
 * rectangle, and since an SVG's content preserves its aspect ratio inside
 * its box by default (`preserveAspectRatio="xMidYMid meet"`), the star
 * artwork itself shrinks to fit the *narrower* dimension and gets centered —
 * rendering as an undersized complete star floating in the left half instead
 * of a same-size star clipped in half. Giving the filled star the same fixed
 * `className` size as the outline star behind it (not derived from its
 * clipping parent) makes it render at full, correct size as an ordinary
 * (non-absolutely-positioned) child of the half-width `overflow-hidden` clip
 * span — which then visually crops its right half away, same size and
 * alignment as the outline star underneath. Caught via a live Chromium
 * screenshot (`next dev` + Playwright), not this file's jsdom suite: jsdom
 * doesn't lay out real box geometry, so the DOM shape
 * (`data-slot="half-star"` present, a nested half-width clip span) looked
 * identical whether or not the visual bug was present — see
 * `star-rating.test.tsx`'s size assertions added alongside this fix.
 *
 * `data-slot="half-star"` on the wrapper is a plain test hook (queried by
 * `container.querySelectorAll` in `star-rating.test.tsx` and the consumer
 * components' own tests) rather than anything the app reads.
 */
function HalfStar({ className }: { className: string }) {
  return (
    <span data-slot="half-star" className={cn("relative inline-block", className)}>
      <Star aria-hidden className={cn(className, "text-muted-foreground")} />
      <span className="absolute inset-y-0 left-0 w-1/2 overflow-hidden">
        <Star aria-hidden className={cn(className, "fill-current text-yellow-500")} />
      </span>
    </span>
  );
}
