import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Same rationale as `trending-filters.test.tsx` for mocking
// `@/i18n/navigation` and `next-intl`.
const replace = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { RecommendationFilters } = await import("./recommendation-filters");

beforeEach(() => {
  replace.mockClear();
});

describe("RecommendationFilters", () => {
  it("renders an 'all' option plus the four catalog types", () => {
    render(<RecommendationFilters />);

    const select = screen.getByLabelText("typeLabel");
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["", "movie", "series", "book", "game"]);
  });

  it("navigates with the selected type", () => {
    render(<RecommendationFilters />);

    fireEvent.change(screen.getByLabelText("typeLabel"), {
      target: { value: "book" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/recommendations",
      query: { type: "book" },
    });
  });

  it("clearing the type back to 'all' omits it from the query", () => {
    render(<RecommendationFilters selectedType="book" />);

    fireEvent.change(screen.getByLabelText("typeLabel"), {
      target: { value: "" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/recommendations",
      query: {},
    });
  });
});
