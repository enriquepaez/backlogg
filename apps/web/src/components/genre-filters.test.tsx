import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Same rationale as `browse-filters.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl`.
const replace = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { GenreFilters } = await import("./genre-filters");

beforeEach(() => {
  replace.mockClear();
});

describe("GenreFilters", () => {
  it("renders an 'all types' option plus one per catalog type", () => {
    render(<GenreFilters />);

    const select = screen.getByLabelText("typeLabel");
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["", "movie", "series", "book", "game"]);
  });

  it("navigates to /genres?type=... when a type is selected", () => {
    render(<GenreFilters />);

    fireEvent.change(screen.getByLabelText("typeLabel"), {
      target: { value: "movie" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/genres",
      query: { type: "movie" },
    });
  });

  it("clearing the type back to 'all' omits it from the query", () => {
    render(<GenreFilters selectedType="movie" />);

    fireEvent.change(screen.getByLabelText("typeLabel"), {
      target: { value: "" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/genres",
      query: {},
    });
  });
});
