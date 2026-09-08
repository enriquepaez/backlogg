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

const { TrendingFilters } = await import("./trending-filters");

beforeEach(() => {
  replace.mockClear();
});

describe("TrendingFilters", () => {
  // FE-68: the filter used to offer movie/series only, so `/trending`'s two
  // other types were unreachable even though the backend has ranked them
  // since backend feature 68.
  it("renders an 'all' option plus all four catalog types", () => {
    render(<TrendingFilters selectedPeriod="week" />);

    const select = screen.getByLabelText("typeLabel");
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["", "movie", "series", "book", "game"]);
  });

  it("labels every option from a Trending.filters message key", () => {
    render(<TrendingFilters selectedPeriod="week" />);

    const select = screen.getByLabelText("typeLabel");
    // The fake translator echoes the key, so this asserts each option's copy
    // is looked up (never hardcoded) — `catalog-types.test.ts` checks the
    // matching es/en strings actually exist.
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.textContent),
    ).toEqual(["all", "movie", "series", "book", "game"]);
  });

  it("navigates with book and game like any other type", () => {
    render(<TrendingFilters selectedPeriod="week" />);

    for (const type of ["book", "game"]) {
      fireEvent.change(screen.getByLabelText("typeLabel"), { target: { value: type } });

      expect(replace).toHaveBeenCalledWith({ pathname: "/trending", query: { type } });
    }
  });

  it("renders day/week options for the period select", () => {
    render(<TrendingFilters selectedPeriod="week" />);

    const select = screen.getByLabelText("periodLabel");
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["day", "week"]);
  });

  it("navigates with the selected type, preserving the current period", () => {
    render(<TrendingFilters selectedPeriod="day" />);

    fireEvent.change(screen.getByLabelText("typeLabel"), {
      target: { value: "movie" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/trending",
      query: { type: "movie", period: "day" },
    });
  });

  it("clearing the type back to 'all' omits it from the query", () => {
    render(<TrendingFilters selectedType="movie" selectedPeriod="week" />);

    fireEvent.change(screen.getByLabelText("typeLabel"), {
      target: { value: "" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/trending",
      query: {},
    });
  });

  it("navigates with the selected period, preserving the current type", () => {
    render(<TrendingFilters selectedType="movie" selectedPeriod="week" />);

    fireEvent.change(screen.getByLabelText("periodLabel"), {
      target: { value: "day" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/trending",
      query: { type: "movie", period: "day" },
    });
  });

  it("omits period from the query when it's the default (week)", () => {
    render(<TrendingFilters selectedType="movie" selectedPeriod="day" />);

    fireEvent.change(screen.getByLabelText("periodLabel"), {
      target: { value: "week" },
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/trending",
      query: { type: "movie" },
    });
  });
});
