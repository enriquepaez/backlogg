import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `catalog-card.test.tsx`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => <a href={href} {...props} />,
}));

const { LibraryBoardCard } = await import("./library-board-card");

describe("LibraryBoardCard", () => {
  it("renders the poster image with empty alt text and the title as visible text", () => {
    render(
      <LibraryBoardCard title="Dune" posterUrl="https://image.tmdb.org/t/p/w500/dune.jpg" />,
    );

    // Decorative here — the title is already rendered as visible text right
    // next to it, same rationale `LibraryBoardCard`'s own doc comment gives
    // for staying deliberately plainer than `CatalogCard`.
    expect(screen.getByAltText("")).toBeInTheDocument();
    expect(screen.getByText("Dune")).toBeInTheDocument();
  });

  it("falls back to a placeholder (no <img>, but still an accessible role=img) when posterUrl is null", () => {
    const { container } = render(<LibraryBoardCard title="Dune" posterUrl={null} />);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Dune" })).toBeInTheDocument();
  });

  it("wraps itself in a link to the item detail page when href is given", () => {
    render(<LibraryBoardCard title="Dune" posterUrl={null} href="/movie/dune-2021" />);

    expect(screen.getByRole("link")).toHaveAttribute("href", "/movie/dune-2021");
  });

  it("renders as a plain (non-link) tile when href is omitted", () => {
    render(<LibraryBoardCard title="Dune" posterUrl={null} />);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
