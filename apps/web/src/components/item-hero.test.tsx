import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ItemHero, type ItemHeroProps } from "./item-hero";

// `ViewerStatusSlot` (FE-20) is a Client Component that fetches its own
// state via `next-intl`'s `useTranslations` and `fetch` — neither works
// under a plain render here, and it isn't what this file tests. Stubbed to a
// marker that only asserts the `type`/`slug` `ItemHero` forwards to it (its
// own behavior is covered by `viewer-status-slot.test.tsx`).
vi.mock("@/components/viewer-status-slot", () => ({
  ViewerStatusSlot: ({ type, slug }: { type: string; slug: string }) => (
    <div data-testid="viewer-status-slot">{`${type}:${slug}`}</div>
  ),
}));

const baseProps: ItemHeroProps = {
  title: "Dune",
  originalTitle: "Dune",
  overview: "Paul Atreides unites with the Fremen of Arrakis.",
  posterUrl: "https://image.tmdb.org/t/p/w500/dune.jpg",
  backdropUrl: "https://image.tmdb.org/t/p/w780/dune-bd.jpg",
  ratingInternal: 7.8,
  ratingCountInternal: 9231,
  genres: ["Science Fiction"],
  fields: [{ label: "Release date", value: "2021-10-22" }],
  viewerStatus: null,
  type: "movie",
  slug: "dune-2021",
  originalTitleLabel: "Original title",
  genresLabel: "Genres",
  ratingInternalLabel: "Backlogg rating",
  noRatingsLabel: "No ratings yet",
};

describe("ItemHero", () => {
  it("renders the title", () => {
    render(<ItemHero {...baseProps} />);

    expect(screen.getByRole("heading", { level: 1, name: "Dune" })).toBeInTheDocument();
  });

  it("omits the original title row when it matches the title", () => {
    render(<ItemHero {...baseProps} originalTitle="Dune" />);

    expect(screen.queryByText(/Original title/)).not.toBeInTheDocument();
  });

  it("shows the original title row when it differs from the title", () => {
    render(<ItemHero {...baseProps} title="Spirited Away" originalTitle="千と千尋の神隠し" />);

    expect(screen.getByText(/Original title/)).toBeInTheDocument();
    expect(screen.getByText(/千と千尋の神隠し/)).toBeInTheDocument();
  });

  it("renders genre pills", () => {
    render(<ItemHero {...baseProps} genres={["Science Fiction", "Adventure"]} />);

    expect(screen.getByText("Science Fiction")).toBeInTheDocument();
    expect(screen.getByText("Adventure")).toBeInTheDocument();
  });

  it("gives genre pills the flat accent color and more visual weight than the other badges (FE-62)", () => {
    render(<ItemHero {...baseProps} genres={["Science Fiction", "Adventure"]} />);

    const scienceFiction = screen.getByText("Science Fiction");
    const adventure = screen.getByText("Adventure");

    // Same accent token on every genre — no per-genre color (FE-62 acceptance).
    expect(scienceFiction).toHaveClass("bg-accent", "text-accent-foreground");
    expect(adventure).toHaveClass("bg-accent", "text-accent-foreground");
    // More weight than the neutral `bg-muted`/`text-xs`/`font-medium` pill this replaces.
    expect(scienceFiction).not.toHaveClass("bg-muted", "text-muted-foreground");
    expect(scienceFiction).toHaveClass("text-sm", "font-semibold");
  });

  it("renders the internal rating rounded to one decimal, with the count", () => {
    render(<ItemHero {...baseProps} ratingInternal={7.756} ratingCountInternal={9231} />);

    expect(screen.getByText("7.8")).toBeInTheDocument();
    expect(screen.getByText("(9231)")).toBeInTheDocument();
  });

  it("renders exactly one rating badge — rating_external is never shown to end users (FE-59)", () => {
    render(<ItemHero {...baseProps} ratingInternal={7.8} ratingCountInternal={9231} />);

    expect(screen.getByText("Backlogg rating")).toBeInTheDocument();
    expect(screen.getAllByText("7.8")).toHaveLength(1);
  });

  it("shows the no-ratings fallback when a rating is null", () => {
    render(<ItemHero {...baseProps} ratingInternal={null} />);

    expect(screen.getByText("No ratings yet")).toBeInTheDocument();
  });

  it("shows the no-ratings fallback (without crashing) when rating_internal is undefined at runtime — a stale Next.js Data Cache entry from before the field existed (`getItem`'s cached JSON predating backend feature 69) can carry an `undefined` value here despite the `number | null` prop type", () => {
    const props = { ...baseProps, ratingInternal: undefined } as unknown as ItemHeroProps;

    render(<ItemHero {...props} />);

    expect(screen.getByText("No ratings yet")).toBeInTheDocument();
  });

  it("renders the overview when present", () => {
    render(<ItemHero {...baseProps} />);

    expect(
      screen.getByText("Paul Atreides unites with the Fremen of Arrakis."),
    ).toBeInTheDocument();
  });

  it("omits the overview paragraph when null", () => {
    const { container } = render(<ItemHero {...baseProps} overview={null} />);

    expect(container.textContent).not.toContain("Paul Atreides");
  });

  it("renders type-specific metadata fields as a definition list", () => {
    render(
      <ItemHero
        {...baseProps}
        fields={[
          { label: "Release date", value: "2021-10-22" },
          { label: "Runtime", value: "155 min" },
        ]}
      />,
    );

    expect(screen.getByText("Release date")).toBeInTheDocument();
    expect(screen.getByText("2021-10-22")).toBeInTheDocument();
    expect(screen.getByText("Runtime")).toBeInTheDocument();
    expect(screen.getByText("155 min")).toBeInTheDocument();
  });

  it("falls back to a placeholder when poster_url is null", () => {
    const { container } = render(<ItemHero {...baseProps} posterUrl={null} />);

    expect(container.querySelector("img[alt='Dune']")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Dune" })).toBeInTheDocument();
  });

  it("forwards type/slug to ViewerStatusSlot", () => {
    render(<ItemHero {...baseProps} type="series" slug="chernobyl" />);

    expect(screen.getByTestId("viewer-status-slot")).toHaveTextContent("series:chernobyl");
  });
});
