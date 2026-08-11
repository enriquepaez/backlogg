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
  it("renders an 'all' option plus movie/series for the type select", () => {
    render(<TrendingFilters selectedPeriod="week" />);

    const select = screen.getByLabelText("typeLabel");
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["", "movie", "series"]);
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
