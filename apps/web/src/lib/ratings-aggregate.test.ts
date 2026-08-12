import { describe, expect, it } from "vitest";

import { recomputeAggregate } from "./ratings-aggregate";

describe("recomputeAggregate", () => {
  it("returns the same reference when the score doesn't change", () => {
    const current = { ratingInternal: 4.2, ratingCountInternal: 87 };
    expect(recomputeAggregate(current, 5, 5)).toBe(current);
    expect(recomputeAggregate(current, null, null)).toBe(current);
  });

  it("adds a new score to an item with no prior ratings", () => {
    expect(recomputeAggregate({ ratingInternal: null, ratingCountInternal: 0 }, null, 4)).toEqual({
      ratingInternal: 4,
      ratingCountInternal: 1,
    });
  });

  it("adds a new score alongside existing ratings", () => {
    // (4.2 * 87 + 5) / 88 = 4.209... -> 4.21
    expect(recomputeAggregate({ ratingInternal: 4.2, ratingCountInternal: 87 }, null, 5)).toEqual({
      ratingInternal: 4.21,
      ratingCountInternal: 88,
    });
  });

  it("replaces an existing score, keeping the count unchanged", () => {
    // (4.2 * 87 - 5 + 1) / 87 = 4.154... -> 4.15
    expect(recomputeAggregate({ ratingInternal: 4.2, ratingCountInternal: 87 }, 5, 1)).toEqual({
      ratingInternal: 4.15,
      ratingCountInternal: 87,
    });
  });

  it("removes a score (delete), decrementing the count", () => {
    // (4.2 * 87 - 5) / 86 = 4.194... -> 4.19
    expect(recomputeAggregate({ ratingInternal: 4.2, ratingCountInternal: 87 }, 5, null)).toEqual({
      ratingInternal: 4.19,
      ratingCountInternal: 86,
    });
  });

  it("falls back to null once the last score is removed", () => {
    expect(recomputeAggregate({ ratingInternal: 5, ratingCountInternal: 1 }, 5, null)).toEqual({
      ratingInternal: null,
      ratingCountInternal: 0,
    });
  });

  it("never lets the count go negative", () => {
    expect(recomputeAggregate({ ratingInternal: null, ratingCountInternal: 0 }, 5, null)).toEqual({
      ratingInternal: null,
      ratingCountInternal: 0,
    });
  });

  it("adds a text-only review (score null) without touching the aggregate", () => {
    const current = { ratingInternal: 4.2, ratingCountInternal: 87 };
    expect(recomputeAggregate(current, null, null)).toBe(current);
  });
});
