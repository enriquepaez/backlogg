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

  it("reserves a 2-line minimum height on the title so 1-line and 2-line titles align across a grid (issue #12)", () => {
    render(
      <CatalogCard title="Hades" posterUrl={null} ratingExternal={null} />,
    );

    expect(screen.getByText("Hades")).toHaveClass("line-clamp-2", "min-h-10");
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

  it("renders the optional footer below the title when provided", () => {
    render(
      <CatalogCard
        title="Dune"
        posterUrl={null}
        ratingExternal={null}
        footer={<p>Because you rated Blade Runner 2049</p>}
      />,
    );

    expect(screen.getByText("Because you rated Blade Runner 2049")).toBeInTheDocument();
  });

  it("omits the footer entirely when not provided", () => {
    const { container } = render(
      <CatalogCard title="Dune" posterUrl={null} ratingExternal={null} />,
    );

    expect(container.querySelector('[data-slot="card-content"]')?.children).toHaveLength(1);
  });

  it("shows the library status badge, colored by status, when libraryStatus and libraryStatusLabel are provided (FE-37)", () => {
    render(
      <CatalogCard
        title="Dune"
        posterUrl={null}
        ratingExternal={null}
        libraryStatus="in_progress"
        libraryStatusLabel="In progress"
      />,
    );

    const badge = screen.getByText("In progress");
    expect(badge).toHaveClass("bg-status-in-progress", "text-status-in-progress-foreground");
  });

  it("omits the library status badge when libraryStatus is not provided", () => {
    render(
      <CatalogCard title="Dune" posterUrl={null} ratingExternal={null} libraryStatusLabel="In progress" />,
    );

    expect(screen.queryByText("In progress")).not.toBeInTheDocument();
  });

  it("omits the library status badge when libraryStatusLabel is not provided", () => {
    render(
      <CatalogCard title="Dune" posterUrl={null} ratingExternal={null} libraryStatus="in_progress" />,
    );

    expect(screen.queryByText("In progress")).not.toBeInTheDocument();
  });
});
