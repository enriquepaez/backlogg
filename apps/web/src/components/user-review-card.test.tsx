import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `feed-pagination.test.tsx`: `Link` from `@/i18n/navigation`
// is mocked to a plain anchor for a synchronous render-based assertion.
vi.mock("@/i18n/navigation", () => ({
  Link: ({
    href,
    children,
    ...props
  }: {
    href: string | object;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : JSON.stringify(href)} {...props}>
      {children}
    </a>
  ),
}));

// `UserReviewCard`/`ReviewStars` render the shared `StarRating`
// (`@/components/star-rating`), which since FE-47 calls `useTranslations`
// itself for its `role="img"` `aria-label` — mocked the same way
// `rating-widget.test.tsx`/`item-reviews.test.tsx` mock `next-intl`, so this
// Server Component's test doesn't need a real `NextIntlClientProvider`.
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
}));

const { UserReviewCard, ReviewStars } = await import("./user-review-card");

const review = {
  id: 1,
  item: { item_type: "MOVIE", title: "Dune", slug: "dune-2021", poster_url: null },
  score: 4,
  review_text: "Great adaptation.",
  created_at: "2026-05-25T02:03:12Z",
  updated_at: "2026-05-25T02:03:12Z",
};

describe("UserReviewCard", () => {
  it("renders the item title as a link to its detail page", () => {
    render(<UserReviewCard review={review} locale="en" dateLabel={(date) => `Reviewed ${date}`} />);

    const link = screen.getByRole("link", { name: "Dune" });
    expect(link).toHaveAttribute("href", "/movie/dune-2021");
  });

  it("renders the review text and the formatted date via dateLabel", () => {
    render(<UserReviewCard review={review} locale="en" dateLabel={(date) => `Reviewed ${date}`} />);

    expect(screen.getByText("Great adaptation.")).toBeInTheDocument();
    expect(screen.getByText("Reviewed May 25, 2026")).toBeInTheDocument();
  });

  it("omits the review text paragraph when there is none", () => {
    render(
      <UserReviewCard
        review={{ ...review, review_text: null }}
        locale="en"
        dateLabel={(date) => date}
      />,
    );

    expect(screen.queryByText("Great adaptation.")).not.toBeInTheDocument();
  });

  it("renders plain text (no link) when the item type is unrecognized", () => {
    render(
      <UserReviewCard
        review={{ ...review, item: { ...review.item, item_type: "unknown" } }}
        locale="en"
        dateLabel={(date) => date}
      />,
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Dune")).toBeInTheDocument();
  });
});

describe("ReviewStars", () => {
  it("renders five stars total regardless of score", () => {
    const { container } = render(<ReviewStars score={3} />);

    expect(container.querySelectorAll("svg")).toHaveLength(5);
  });

  it("renders no filled stars when the score is null", () => {
    const { container } = render(<ReviewStars score={null} />);

    expect(container.querySelectorAll("svg.fill-current")).toHaveLength(0);
  });

  it("renders a half-filled star for a .5 score, without regressing whole-number scores", () => {
    const wholeNumber = render(<ReviewStars score={4} />);
    expect(wholeNumber.container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0);
    wholeNumber.unmount();

    const halfPoint = render(<ReviewStars score={3.5} />);
    expect(halfPoint.container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);
  });

  // FE-47: `ReviewStars` is a thin wrapper around `StarRating` — confirms
  // this call site (a Server Component, `user-review-card.tsx`) inherits the
  // `role="img"` + `aria-label` fix without any changes of its own.
  it("exposes the score to assistive tech via role=img + aria-label", () => {
    const { container } = render(<ReviewStars score={4} />);

    expect(container.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(
      'ariaLabel:{"value":4}',
    );
  });

  it("falls back to an 'unrated' aria-label when the score is null", () => {
    const { container } = render(<ReviewStars score={null} />);

    expect(container.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(
      "unratedAriaLabel",
    );
  });
});
