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

const { FeedEntryList } = await import("./feed-entry-list");

const duneEntry = {
  id: 1,
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
});
