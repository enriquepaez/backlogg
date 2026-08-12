export type RatingAggregate = {
  ratingInternal: number | null;
  ratingCountInternal: number;
};

/**
 * Client-side optimistic recompute of an item's `rating_internal`/
 * `rating_count_internal` after the viewer's own PUT/DELETE
 * `.../rating` action (FE-18 acceptance: "agregados actualizados").
 *
 * The `PUT`/`DELETE .../rating` responses only carry the caller's own
 * `RatingOut` row — the backend recomputes the item's aggregates server-side
 * (`docs/api.md`: "Tras cada upsert se recalculan `rating_internal` (AVG) y
 * `rating_count_internal` (COUNT)") but doesn't return them, and re-fetching
 * the item detail page's own SSR/ISR data on every action would either
 * require making the whole public, ISR-cached item detail page dynamic (see
 * `src/lib/catalog.ts`'s `ITEM_REVALIDATE_SECONDS`) or wait out that cache
 * window — neither gives the "reflected right after the action" UX FE-18
 * asks for. This is therefore only ever an approximation of the server's
 * AVG/COUNT (mirrors `rating_internal NUMERIC(3,2)`, `docs/schema.md`): it
 * does not see other users rating the item concurrently. The next full page
 * load, once the ISR window rolls over, reconciles with the real value.
 *
 * `previousScore`/`nextScore` are the caller's own score before/after the
 * action (`null` for "no score" — a fresh rating, a text-only review, or a
 * delete). Passing the same value for both is a no-op (returns `current`
 * unchanged) — covers editing only `review_text` while keeping the same
 * score.
 */
export function recomputeAggregate(
  current: RatingAggregate,
  previousScore: number | null,
  nextScore: number | null,
): RatingAggregate {
  if (previousScore === nextScore) {
    return current;
  }

  const currentTotal = (current.ratingInternal ?? 0) * current.ratingCountInternal;
  let total = currentTotal;
  let count = current.ratingCountInternal;

  if (previousScore !== null) {
    total -= previousScore;
    count -= 1;
  }
  if (nextScore !== null) {
    total += nextScore;
    count += 1;
  }

  count = Math.max(count, 0);
  return {
    ratingInternal: count > 0 ? round2(total / count) : null,
    ratingCountInternal: count,
  };
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
