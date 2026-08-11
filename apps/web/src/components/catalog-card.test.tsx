import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// `@/i18n/navigation`'s `Link` doesn't resolve under plain Vitest/jsdom (see
// `catalog-section.test.tsx` for the same mock + rationale) — needed here
// too now that `CatalogCard` conditionally wraps itself in that `Link`
// (FE-10, `href` prop).
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => (
    <a href={href} {...props} />
  ),
}));

const { CatalogCard } = await import("./catalog-card");

describe("CatalogCard", () => {
  it("renders the poster image with the title as alt text", () => {
    render(
      <CatalogCard
        title="Dune"
        posterUrl="https://image.tmdb.org/t/p/w500/dune.jpg"
        ratingExternal={7.8}
      />,
    );

    expect(screen.getByRole("img", { name: "Dune" })).toBeInTheDocument();
  });

  it("renders the rating rounded to one decimal", () => {
    render(
      <CatalogCard
        title="Dune"
        posterUrl="https://image.tmdb.org/t/p/w500/dune.jpg"
        ratingExternal={7.756}
      />,
    );

    expect(screen.getByText("7.8")).toBeInTheDocument();
  });

  it("omits the rating badge when rating_external is null", () => {
    render(
      <CatalogCard title="Dune" posterUrl={null} ratingExternal={null} />,
    );

    expect(screen.queryByText(/\d\.\d/)).not.toBeInTheDocument();
  });

  it("falls back to a placeholder (no <img>, but still an accessible role=img) when poster_url is null", () => {
    const { container } = render(
      <CatalogCard title="Dune" posterUrl={null} ratingExternal={null} />,
    );

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Dune" })).toBeInTheDocument();
  });

  it("shows the type badge when provided", () => {
    render(
      <CatalogCard
        title="Chernobyl"
        posterUrl={null}
        ratingExternal={null}
        typeLabel="Series"
      />,
    );

    expect(screen.getByText("Series")).toBeInTheDocument();
  });

  it("renders the title text visibly", () => {
    render(
      <CatalogCard title="Hades" posterUrl={null} ratingExternal={null} />,
    );

    expect(screen.getByText("Hades")).toBeInTheDocument();
  });

  it("wraps itself in a link to the item detail page when href is given", () => {
    render(
      <CatalogCard
        title="Dune"
        posterUrl={null}
        ratingExternal={null}
        href="/movie/dune-2021"
      />,
    );

    expect(screen.getByRole("link")).toHaveAttribute("href", "/movie/dune-2021");
  });

  it("renders as a plain (non-link) tile when href is omitted", () => {
    render(
      <CatalogCard title="Dune" posterUrl={null} ratingExternal={null} />,
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
