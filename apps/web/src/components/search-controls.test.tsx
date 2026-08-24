import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Same rationale as `browse-filters.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl`.
const replace = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { SearchControls } = await import("./search-controls");

beforeEach(() => {
  replace.mockClear();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

// Re-scope of FE-35 (`browse_search_filters`): date range and the
// external-rating range live behind the "More filters" popover trigger —
// open it first so their (still visibly labeled) inputs are mounted, same
// pattern `admin-catalog-filters.test.tsx` uses for its own popover.
async function openMoreFilters() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /filters\.moreFilters/ }));
  });
}

describe("SearchControls", () => {
  it("does not navigate on mount", () => {
    render(<SearchControls initialQuery="dune" />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(replace).not.toHaveBeenCalled();
  });

  it("renders an empty status region (no pending navigation) by default", () => {
    render(<SearchControls initialQuery="dune" />);

    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("debounces navigation while typing, firing once after the pause", () => {
    render(<SearchControls initialQuery="" />);

    const input = screen.getByLabelText("inputLabel");
    fireEvent.change(input, { target: { value: "d" } });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    fireEvent.change(input, { target: { value: "du" } });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    fireEvent.change(input, { target: { value: "dune" } });

    act(() => {
      vi.advanceTimersByTime(399);
    });
    expect(replace).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith({ pathname: "/search", query: { q: "dune" } });
  });

  it("omits q from the query once the input is cleared", () => {
    render(<SearchControls initialQuery="dune" />);

    fireEvent.change(screen.getByLabelText("inputLabel"), { target: { value: "" } });
    act(() => {
      vi.advanceTimersByTime(400);
    });

    expect(replace).toHaveBeenCalledWith({ pathname: "/search", query: {} });
  });

  it("navigates immediately (no debounce) when the type filter changes, preserving q", () => {
    render(<SearchControls initialQuery="dune" />);

    fireEvent.change(screen.getByLabelText("filters.typeLabel"), { target: { value: "movie" } });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/search",
      query: { q: "dune", type: "movie" },
    });
  });

  it("clearing the type filter back to 'all' omits it from the query", () => {
    render(<SearchControls initialQuery="dune" initialType="movie" />);

    fireEvent.change(screen.getByLabelText("filters.typeLabel"), { target: { value: "" } });

    expect(replace).toHaveBeenCalledWith({ pathname: "/search", query: { q: "dune" } });
  });

  it("shows a badge on the more-filters trigger counting how many advanced groups are active", async () => {
    render(<SearchControls initialQuery="" />);

    expect(screen.getByRole("button", { name: /filters\.moreFilters/ })).not.toHaveTextContent(/[12]/);

    await openMoreFilters();
    fireEvent.change(screen.getByLabelText("filters.dateFromLabel"), { target: { value: "2020-01-01" } });

    expect(screen.getByRole("button", { name: /filters\.moreFilters/ })).toHaveTextContent("1");
  });

  it("debounces the date range, navigating with both bounds once valid, preserving q", async () => {
    render(<SearchControls initialQuery="dune" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("filters.dateFromLabel"), { target: { value: "2020-01-01" } });
    fireEvent.change(screen.getByLabelText("filters.dateToLabel"), { target: { value: "2021-12-31" } });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/search",
      query: { q: "dune", date_from: "2020-01-01", date_to: "2021-12-31" },
    });
  });

  it("shows an inline error and withholds the pending edit when date_from is after date_to", async () => {
    render(<SearchControls initialQuery="dune" initialDateFrom="2020-01-01" initialDateTo="2020-06-01" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("filters.dateFromLabel"), { target: { value: "2021-01-01" } });

    expect(screen.getByRole("alert")).toHaveTextContent("filters.dateRangeInvalid");

    act(() => {
      vi.advanceTimersByTime(300);
    });

    // The invalid pending edit is not sent — falling back to the committed
    // range equals the current URL, so no navigation should have fired.
    expect(replace).not.toHaveBeenCalled();
  });

  it("still lets an unrelated q edit navigate while the date range is invalid", async () => {
    render(<SearchControls initialQuery="dune" initialDateFrom="2020-01-01" initialDateTo="2020-06-01" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("filters.dateFromLabel"), { target: { value: "2021-01-01" } });
    fireEvent.change(screen.getByLabelText("inputLabel"), { target: { value: "matrix" } });

    act(() => {
      vi.advanceTimersByTime(400);
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/search",
      query: { q: "matrix", date_from: "2020-01-01", date_to: "2020-06-01" },
    });
  });

  it("debounces the external rating range, navigating with both bounds once valid", async () => {
    render(<SearchControls initialQuery="dune" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("filters.ratingExternalMinLabel"), { target: { value: "6.5" } });
    fireEvent.change(screen.getByLabelText("filters.ratingExternalMaxLabel"), { target: { value: "8" } });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/search",
      query: { q: "dune", rating_external_min: "6.5", rating_external_max: "8" },
    });
  });

  it("shows an inline error when the external rating min is greater than max", async () => {
    render(<SearchControls initialQuery="dune" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("filters.ratingExternalMinLabel"), { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("filters.ratingExternalMaxLabel"), { target: { value: "5" } });

    expect(screen.getByText("filters.ratingExternalRangeInvalid")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).not.toHaveBeenCalled();
  });

  it("combines the date range and the external rating range with q/type in one navigation", async () => {
    render(<SearchControls initialQuery="dune" initialType="movie" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("filters.dateFromLabel"), { target: { value: "2000-01-01" } });
    fireEvent.change(screen.getByLabelText("filters.ratingExternalMinLabel"), { target: { value: "5" } });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/search",
      query: { q: "dune", type: "movie", date_from: "2000-01-01", rating_external_min: "5" },
    });
  });

  it("hides the clear-filters button when no advanced filter is active", async () => {
    render(<SearchControls initialQuery="dune" />);
    await openMoreFilters();

    expect(screen.queryByRole("button", { name: "filters.clearFilters" })).not.toBeInTheDocument();
  });

  it("clears the date range and rating range in one click, keeping q/type intact", async () => {
    render(
      <SearchControls
        initialQuery="dune"
        initialType="movie"
        initialDateFrom="2020-01-01"
        initialDateTo="2020-06-01"
        initialRatingExternalMin={5}
        initialRatingExternalMax={8}
      />,
    );
    await openMoreFilters();

    fireEvent.click(screen.getByRole("button", { name: "filters.clearFilters" }));

    expect(replace).toHaveBeenCalledWith({
      pathname: "/search",
      query: { q: "dune", type: "movie" },
    });

    expect(screen.getByLabelText("filters.dateFromLabel")).toHaveValue("");
    expect(screen.getByLabelText("filters.dateToLabel")).toHaveValue("");
    expect(screen.getByLabelText("filters.ratingExternalMinLabel")).toHaveValue(null);
    expect(screen.getByLabelText("filters.ratingExternalMaxLabel")).toHaveValue(null);

    // The debounce effect must not fire a second, stale navigation using the
    // (still unchanged, since `replace` is mocked) old committed values —
    // the clear action's own immediate `replace` call above must be the only one.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(replace).toHaveBeenCalledTimes(1);
  });
});
