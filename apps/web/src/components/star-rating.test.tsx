import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StarRating, starFillAt } from "./star-rating";

describe("starFillAt", () => {
  it("marks every position up to the integer part of the score as full", () => {
    expect(starFillAt(1, 3)).toBe("full");
    expect(starFillAt(3, 3)).toBe("full");
    expect(starFillAt(4, 3)).toBe("empty");
  });

  it("marks the position right after the integer part as half when the score has a .5 fraction", () => {
    expect(starFillAt(4, 3.5)).toBe("half");
    expect(starFillAt(3, 3.5)).toBe("full");
    expect(starFillAt(5, 3.5)).toBe("empty");
  });

  it("marks every position empty when the score is null", () => {
    expect(starFillAt(1, null)).toBe("empty");
    expect(starFillAt(5, null)).toBe("empty");
  });

  it("handles a whole-number score of 5 with no half star", () => {
    expect(starFillAt(5, 5)).toBe("full");
  });

  it("handles the lowest half-point score (0.5 is out of range, 1 is the floor)", () => {
    expect(starFillAt(1, 1)).toBe("full");
    expect(starFillAt(2, 1)).toBe("empty");
  });
});

describe("StarRating", () => {
  it("renders five stars total for an integer score, with no half-star marker", () => {
    const { container } = render(<StarRating score={3} />);

    expect(container.querySelectorAll("svg")).toHaveLength(5);
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0);
  });

  it("renders no filled stars when the score is null", () => {
    const { container } = render(<StarRating score={null} />);

    expect(container.querySelectorAll("svg.fill-current")).toHaveLength(0);
  });

  it("renders exactly one half-star marker for a X.5 score", () => {
    const { container } = render(<StarRating score={3.5} />);

    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);
  });

  it("does not regress integer scores: 4.0 renders the same as before (four full stars, one empty, no half marker)", () => {
    const { container } = render(<StarRating score={4} />);

    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0);
    expect(container.querySelectorAll("svg.fill-current")).toHaveLength(4);
  });

  // Regression test for a post-launch visual bug (FE-44 QA follow-up): the
  // filled half of a half-star was sized with `size-full` (100% of its
  // *clipping* half-width span, not of the icon's actual intended size),
  // which a real browser renders as an undersized, off-center star instead
  // of a same-size star cropped in half — confirmed via a live Chromium
  // screenshot against `next dev` (see `star-rating.tsx`'s `HalfStar` doc
  // comment). jsdom performs no real box layout, so a `data-slot="half-star"`
  // presence check (the only assertion this suite had before) stays green
  // whether or not this bug is present — that's exactly the gap that let the
  // original bug and its "fix" both ship unnoticed. Asserting the actual
  // size class applied to each of the two stacked star icons pins the bug at
  // its source: both must carry the *same* explicit size the caller passed
  // (matching `starClassName`), never the old `size-full`.
  it("sizes both the outline and filled star of a half-star icon identically to the caller's starClassName (not size-full)", () => {
    const { container } = render(<StarRating score={3.5} starClassName="size-9" />);

    const halfStar = container.querySelector('[data-slot="half-star"]');
    expect(halfStar).not.toBeNull();

    const [outlineStar, filledStar] = halfStar!.querySelectorAll("svg");
    expect(outlineStar).not.toBeUndefined();
    expect(filledStar).not.toBeUndefined();

    for (const svg of [outlineStar, filledStar]) {
      expect(svg.getAttribute("class")).toContain("size-9");
      expect(svg.getAttribute("class")).not.toContain("size-full");
    }
  });
});
