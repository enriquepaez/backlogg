import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `catalog-section.test.tsx` for mocking `@/i18n/navigation`'s `Link`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => {
    const target =
      typeof href === "object" && href !== null
        ? `${(href as { pathname: string }).pathname}?${new URLSearchParams(
            (href as { query?: Record<string, string> }).query ?? {},
          ).toString()}`
        : (href as string);
    return <a href={target} {...props} />;
  },
}));

const { GenreSections } = await import("./genre-sections");

const typeLabels = {
  movie: "Movies",
  series: "Series",
  book: "Books",
  game: "Games",
};

const genres = [
  { name: "Science Fiction", slug: "science-fiction", count: 42, item_type: "movie" as const },
  { name: "Drama", slug: "drama", count: 12, item_type: "series" as const },
];

describe("GenreSections", () => {
  it("groups genres into one section per type, in catalog-type order", () => {
    render(<GenreSections genres={genres} typeLabels={typeLabels} />);

    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings).toEqual(["Movies", "Series"]);
  });

  it("omits sections for types with no genres", () => {
    render(<GenreSections genres={genres} typeLabels={typeLabels} />);

    expect(screen.queryByRole("heading", { name: "Books" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Games" })).not.toBeInTheDocument();
  });

  it("links each genre to /browse/{type}?genre=slug", () => {
    render(<GenreSections genres={genres} typeLabels={typeLabels} />);

    const link = screen.getByRole("link", { name: "Science Fiction (42)" });
    expect(link).toHaveAttribute("href", "/browse/movie?genre=science-fiction");
  });

  it("renders a single unlabelled section when selectedType is set", () => {
    render(
      <GenreSections
        genres={genres.filter((g) => g.item_type === "movie")}
        selectedType="movie"
        typeLabels={typeLabels}
      />,
    );

    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Science Fiction (42)" })).toBeInTheDocument();
  });
});
