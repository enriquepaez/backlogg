import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Same rationale as `catalog-section.test.tsx` for mocking `@/i18n/navigation`
// (its `Link`/`useRouter` pull in `next/navigation`'s client-only build,
// which doesn't resolve under plain Vitest/jsdom) — `useTranslations` is
// mocked to an identity function so assertions can match on message keys
// without needing a real `NextIntlClientProvider`.
const replace = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { BrowseFilters } = await import("./browse-filters");

const genres = [
  { name: "Science Fiction", slug: "science-fiction", count: 3 },
  { name: "Drama", slug: "drama", count: 5 },
];

beforeEach(() => {
  replace.mockClear();
});

describe("BrowseFilters", () => {
  it("renders an 'all genres' option plus one per genre", () => {
    render(
      <BrowseFilters type="movie" genres={genres} selectedSort="rating_desc" />,
    );

    const genreSelect = screen.getByLabelText("genreLabel");
    expect(
      Array.from(genreSelect.querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["", "science-fiction", "drama"]);
  });

  it("navigates with the selected genre and resets the page", () => {
    render(
      <BrowseFilters type="movie" genres={genres} selectedSort="rating_desc" />,
    );

    fireEvent.change(screen.getByLabelText("genreLabel"), {
      target: { value: "science-fiction" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/browse/movie",
      query: { genre: "science-fiction" },
    });
  });

  it("clearing the genre back to 'all' omits it from the query", () => {
    render(
      <BrowseFilters
        type="movie"
        genres={genres}
        selectedGenre="drama"
        selectedSort="rating_desc"
      />,
    );

    fireEvent.change(screen.getByLabelText("genreLabel"), {
      target: { value: "" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/browse/movie",
      query: {},
    });
  });

  it("navigates with the selected sort, preserving the current genre", () => {
    render(
      <BrowseFilters
        type="movie"
        genres={genres}
        selectedGenre="drama"
        selectedSort="rating_desc"
      />,
    );

    fireEvent.change(screen.getByLabelText("sortLabel"), {
      target: { value: "date_desc" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/browse/movie",
      query: { genre: "drama", sort: "date_desc" },
    });
  });

  it("omits sort from the query when it's the default (rating_desc)", () => {
    render(
      <BrowseFilters
        type="movie"
        genres={genres}
        selectedGenre="drama"
        selectedSort="date_desc"
      />,
    );

    fireEvent.change(screen.getByLabelText("sortLabel"), {
      target: { value: "rating_desc" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/browse/movie",
      query: { genre: "drama" },
    });
  });
});
