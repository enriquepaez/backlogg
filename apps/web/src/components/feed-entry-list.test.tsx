import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `follow-user-list.test.tsx`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => <a href={href} {...props} />,
}));

vi.mock("next-intl/server", () => ({
  getTranslations:
    async () =>
    (key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${JSON.stringify(values)}` : key,
}));

// `FeedEntryStars` renders the shared `StarRating` (`@/components/star-rating`),
// which since FE-47 calls the client-side `useTranslations` (from `next-intl`,
// not `next-intl/server`) itself for its `role="img"` `aria-label` — mocked
// the same way `rating-widget.test.tsx`/`item-reviews.test.tsx` mock it, so
// this Server Component's test doesn't need a real `NextIntlClientProvider`.
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
}));

const { FeedEntryList } = await import("./feed-entry-list");

const duneEntry = {
  id: 1,
  event_type: "rating_created" as const,
  author: { username: "bob", display_name: "Bob", avatar_url: null },
  item: {
    item_type: "MOVIE",
    title: "Dune",
    slug: "dune-2021",
    poster_url: "https://image.tmdb.org/t/p/w500/dune.jpg",
  },
  score: 4,
  review_text: "A stunning adaptation.",
  like_count: 12,
  created_at: "2026-05-25T18:04:11Z",
};

describe("FeedEntryList", () => {
  it("renders the author's name linked to their public profile", async () => {
    render(await FeedEntryList({ entries: [duneEntry], locale: "en" }));

    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Bob/ })).toHaveAttribute("href", "/u/bob");
  });

  it("renders the item's title linked to its detail page", async () => {
    render(await FeedEntryList({ entries: [duneEntry], locale: "en" }));

    expect(screen.getByRole("link", { name: "Dune" })).toHaveAttribute("href", "/movie/dune-2021");
  });

  it("renders the review text and the like count", async () => {
    render(await FeedEntryList({ entries: [duneEntry], locale: "en" }));

    expect(screen.getByText("A stunning adaptation.")).toBeInTheDocument();
    expect(screen.getByText('likeCount:{"count":12}')).toBeInTheDocument();
  });

  it("omits the review text paragraph when review_text is null", async () => {
    render(
      await FeedEntryList({ entries: [{ ...duneEntry, review_text: null }], locale: "en" }),
    );

    expect(screen.queryByText("A stunning adaptation.")).not.toBeInTheDocument();
  });

  it("renders a half-filled star for an entry with a .5 score", async () => {
    const { container } = render(
      await FeedEntryList({ entries: [{ ...duneEntry, score: 3.5 }], locale: "en" }),
    );

    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);
  });

  it("renders no half-star marker for a whole-number score (no regression)", async () => {
    const { container } = render(await FeedEntryList({ entries: [duneEntry], locale: "en" }));

    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0);
  });

  // FE-47: `FeedEntryStars` is a thin wrapper around `StarRating` — confirms
  // this call site (a Server Component, `feed-entry-list.tsx`) inherits the
  // `role="img"` + `aria-label` fix without any changes of its own.
  it("exposes the entry's score to assistive tech via role=img + aria-label", async () => {
    const { container } = render(await FeedEntryList({ entries: [duneEntry], locale: "en" }));

    expect(container.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(
      'ariaLabel:{"value":4}',
    );
  });

  it("renders no stars at all for a text-only review (null score)", async () => {
    const { container } = render(
      await FeedEntryList({ entries: [{ ...duneEntry, score: null }], locale: "en" }),
    );

    // lucide-react tags each icon's <svg> with a `lucide-<name>` class
    // (e.g. `lucide-star`/`lucide-heart`) — scope the assertion to stars so
    // the entry's own (unrelated) Heart like-count icon doesn't count.
    expect(container.querySelectorAll("svg.lucide-star")).toHaveLength(0);
  });

  it("renders one card per entry", async () => {
    const carolEntry = {
      ...duneEntry,
      id: 2,
      author: { username: "carol", display_name: null, avatar_url: null },
    };

    render(await FeedEntryList({ entries: [duneEntry, carolEntry], locale: "en" }));

    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("carol")).toBeInTheDocument();
  });

  it("falls back to a plain (non-linked) title for an unrecognized item_type", async () => {
    render(
      await FeedEntryList({
        entries: [{ ...duneEntry, item: { ...duneEntry.item, item_type: "PODCAST" } }],
        locale: "en",
      }),
    );

    expect(screen.getByText("Dune")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dune" })).not.toBeInTheDocument();
  });

  describe("status_completed entries", () => {
    const completedEntry = {
      id: 3,
      event_type: "status_completed" as const,
      author: { username: "bob", display_name: "Bob", avatar_url: null },
      item: {
        item_type: "MOVIE",
        title: "Dune",
        slug: "dune-2021",
        poster_url: "https://image.tmdb.org/t/p/w500/dune.jpg",
      },
      score: null,
      review_text: null,
      like_count: null,
      created_at: "2026-05-25T18:04:11Z",
    };

    it("renders the author and item like any other entry", async () => {
      render(await FeedEntryList({ entries: [completedEntry], locale: "en" }));

      expect(screen.getByRole("link", { name: /Bob/ })).toHaveAttribute("href", "/u/bob");
      expect(screen.getByRole("link", { name: "Dune" })).toHaveAttribute("href", "/movie/dune-2021");
    });

    it("uses the completed-specific date label instead of the review one", async () => {
      render(await FeedEntryList({ entries: [completedEntry], locale: "en" }));

      expect(
        screen.getByText('completedDateLabel:{"date":"May 25, 2026"}'),
      ).toBeInTheDocument();
      expect(screen.queryByText(/^dateLabel:/)).not.toBeInTheDocument();
    });

    it("shows a completed badge instead of stars, review text or a like count", async () => {
      render(await FeedEntryList({ entries: [completedEntry], locale: "en" }));

      expect(screen.getByText("completedBadge")).toBeInTheDocument();
      expect(screen.queryByText(/^likeCount:/)).not.toBeInTheDocument();
    });

    it("renders rating_created and status_completed entries side by side", async () => {
      render(await FeedEntryList({ entries: [duneEntry, completedEntry], locale: "en" }));

      expect(screen.getByText('likeCount:{"count":12}')).toBeInTheDocument();
      expect(screen.getByText("completedBadge")).toBeInTheDocument();
    });
  });
});
