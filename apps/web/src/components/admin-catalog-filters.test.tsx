import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Same rationale as `admin-users-directory-panel.test.tsx` for mocking `next-intl`.
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
}));

const replace = vi.fn();
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace }),
}));

const { AdminCatalogFilters } = await import("./admin-catalog-filters");

const genres = [
  { name: "Action", slug: "action", count: 12 },
  { name: "Drama", slug: "drama", count: 5 },
];

beforeEach(() => {
  replace.mockClear();
});

// Fake timers are opted into per-test (only where the debounce itself is
// under test) rather than globally: Radix `Select`'s `findByRole` polling
// (used by `selectOption` below) relies on real timers to resolve.
afterEach(() => {
  vi.useRealTimers();
});

// Same pattern `admin-users-directory-panel.test.tsx` uses for opening a
// Radix `Select` in jsdom.
async function selectOption(triggerId: string, optionName: string) {
  await act(async () => {
    fireEvent.click(document.getElementById(triggerId)!);
  });
  await act(async () => {
    fireEvent.click(await screen.findByRole("option", { name: optionName }));
  });
}

// Fifth pass: date range and both rating ranges moved behind the "More
// filters" popover trigger — open it first so their (still visibly labeled)
// inputs are mounted before interacting with them, same pattern used for
// Radix `Select` above but for `Popover`.
async function openMoreFilters() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /moreFilters/ }));
  });
}

describe("AdminCatalogFilters", () => {
  it("shows a visible label above sort, kept out of the compact toolbar", () => {
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);

    expect(screen.getByText("sortLabel")).toBeInTheDocument();
  });

  it("still gives search and genre a proper accessible name even though their label is visually hidden", () => {
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);

    expect(screen.getByLabelText("searchLabel")).toBeInTheDocument();
    expect(screen.getByLabelText("genreLabel")).toBeInTheDocument();
  });

  it("shows a visible label above each range field inside the more-filters popover", async () => {
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);

    await openMoreFilters();

    expect(screen.getByText("dateFromLabel")).toBeInTheDocument();
    expect(screen.getByText("dateToLabel")).toBeInTheDocument();
    expect(screen.getByText("ratingInternalMinLabel")).toBeInTheDocument();
    expect(screen.getByText("ratingInternalMaxLabel")).toBeInTheDocument();
    expect(screen.getByText("ratingExternalMinLabel")).toBeInTheDocument();
    expect(screen.getByText("ratingExternalMaxLabel")).toBeInTheDocument();
  });

  it("shows a badge on the more-filters trigger counting how many advanced groups are active", async () => {
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);

    expect(screen.getByRole("button", { name: /moreFilters/ })).not.toHaveTextContent(/[123]/);

    await openMoreFilters();
    fireEvent.change(screen.getByLabelText("dateFromLabel"), { target: { value: "2020-01-01" } });

    expect(screen.getByRole("button", { name: /moreFilters/ })).toHaveTextContent("1");
  });

  it("navigates to the type's admin route with the chosen genre and resets sort omission", async () => {
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);

    await selectOption("admin-catalog-genre-movie", "Drama (5)");

    expect(replace).toHaveBeenCalledWith({ pathname: "/admin/movies", query: { genre: "drama" } });
  });

  it("navigates with the chosen sort, keeping the current genre", async () => {
    render(<AdminCatalogFilters type="series" genres={genres} selectedGenre="action" selectedSort="rating_desc" />);

    await selectOption("admin-catalog-sort-series", "sort.title_asc");

    expect(replace).toHaveBeenCalledWith({
      pathname: "/admin/series",
      query: { genre: "action", sort: "title_asc" },
    });
  });

  it("uses the correct base path per type", async () => {
    render(<AdminCatalogFilters type="game" genres={genres} selectedSort="rating_desc" />);

    await selectOption("admin-catalog-genre-game", "Action (12)");

    expect(replace).toHaveBeenCalledWith({ pathname: "/admin/games", query: { genre: "action" } });
  });

  it("does not navigate on mount", () => {
    vi.useFakeTimers();
    render(
      <AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" selectedSearch="dune" />,
    );

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(replace).not.toHaveBeenCalled();
  });

  it("debounces the search input, navigating once after the pause", () => {
    vi.useFakeTimers();
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);

    const input = screen.getByLabelText("searchLabel");
    fireEvent.change(input, { target: { value: "dun" } });
    act(() => {
      vi.advanceTimersByTime(150);
    });
    fireEvent.change(input, { target: { value: "dune" } });

    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(replace).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith({
      pathname: "/admin/movies",
      query: { search: "dune" },
    });
  });

  it("debounces the date range, navigating with both bounds once valid", async () => {
    vi.useFakeTimers();
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("dateFromLabel"), { target: { value: "2020-01-01" } });
    fireEvent.change(screen.getByLabelText("dateToLabel"), { target: { value: "2021-12-31" } });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/admin/movies",
      query: { date_from: "2020-01-01", date_to: "2021-12-31" },
    });
  });

  it("shows an inline error and withholds the pending edit when date_from is after date_to", async () => {
    vi.useFakeTimers();
    render(
      <AdminCatalogFilters
        type="movie"
        genres={genres}
        selectedSort="rating_desc"
        selectedDateFrom="2020-01-01"
        selectedDateTo="2020-06-01"
      />,
    );
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("dateFromLabel"), { target: { value: "2021-01-01" } });

    expect(screen.getByRole("alert")).toHaveTextContent("dateRangeInvalid");

    act(() => {
      vi.advanceTimersByTime(300);
    });

    // The invalid pending edit is not sent — no navigation should have fired
    // at all, since falling back to the committed range equals the current URL.
    expect(replace).not.toHaveBeenCalled();
  });

  it("still lets an unrelated genre change navigate while the date range is invalid", async () => {
    render(
      <AdminCatalogFilters
        type="movie"
        genres={genres}
        selectedSort="rating_desc"
        selectedDateFrom="2020-01-01"
        selectedDateTo="2020-06-01"
      />,
    );
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("dateFromLabel"), { target: { value: "2021-01-01" } });
    await selectOption("admin-catalog-genre-movie", "Drama (5)");

    expect(replace).toHaveBeenCalledWith({
      pathname: "/admin/movies",
      query: { genre: "drama", date_from: "2020-01-01", date_to: "2020-06-01" },
    });
  });

  it("debounces the rating_internal range, navigating with both bounds once valid", async () => {
    vi.useFakeTimers();
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("ratingInternalMinLabel"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("ratingInternalMaxLabel"), { target: { value: "4" } });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/admin/movies",
      query: { rating_internal_min: "2", rating_internal_max: "4" },
    });
  });

  it("shows an inline error when rating_internal_min is greater than rating_internal_max", async () => {
    vi.useFakeTimers();
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("ratingInternalMinLabel"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("ratingInternalMaxLabel"), { target: { value: "2" } });

    expect(screen.getByText("ratingInternalRangeInvalid")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).not.toHaveBeenCalled();
  });

  it("debounces the rating_external range independently from rating_internal", async () => {
    vi.useFakeTimers();
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("ratingExternalMinLabel"), { target: { value: "6.5" } });
    fireEvent.change(screen.getByLabelText("ratingExternalMaxLabel"), { target: { value: "8" } });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/admin/movies",
      query: { rating_external_min: "6.5", rating_external_max: "8" },
    });
  });

  it("hides the clear-filters button when no filter is active", () => {
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" />);

    expect(screen.queryByRole("button", { name: "clearFilters" })).not.toBeInTheDocument();
  });

  it("shows a clear-filters button, separate from the label text used for the actual filters, once a filter is active", () => {
    render(<AdminCatalogFilters type="movie" genres={genres} selectedGenre="action" selectedSort="rating_desc" />);

    expect(screen.getByRole("button", { name: "clearFilters" })).toBeInTheDocument();
  });

  it("clears every filter and sort in one click, resetting the local fields and navigating to the base path with no query params", async () => {
    vi.useFakeTimers();
    render(
      <AdminCatalogFilters
        type="movie"
        genres={genres}
        selectedGenre="action"
        selectedSort="title_asc"
        selectedSearch="dune"
        selectedDateFrom="2020-01-01"
        selectedDateTo="2020-06-01"
        selectedRatingInternalMin={2}
        selectedRatingInternalMax={4}
        selectedRatingExternalMin={5}
        selectedRatingExternalMax={8}
      />,
    );
    await openMoreFilters();

    fireEvent.click(screen.getByRole("button", { name: "clearFilters" }));

    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith({ pathname: "/admin/movies", query: {} });

    expect(screen.getByLabelText("searchLabel")).toHaveValue("");
    expect(screen.getByLabelText("dateFromLabel")).toHaveValue("");
    expect(screen.getByLabelText("dateToLabel")).toHaveValue("");
    expect(screen.getByLabelText("ratingInternalMinLabel")).toHaveValue(null);
    expect(screen.getByLabelText("ratingInternalMaxLabel")).toHaveValue(null);
    expect(screen.getByLabelText("ratingExternalMinLabel")).toHaveValue(null);
    expect(screen.getByLabelText("ratingExternalMaxLabel")).toHaveValue(null);

    // The debounce effect must not fire a second, stale navigation using the
    // (still unchanged in this test, since `replace` is mocked) old genre/sort
    // props — the clear action's own immediate `replace` call above must be
    // the only one.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it("still debounces a normal edit made right after clearing filters", () => {
    vi.useFakeTimers();
    render(<AdminCatalogFilters type="movie" genres={genres} selectedSort="rating_desc" selectedSearch="dune" />);

    fireEvent.click(screen.getByRole("button", { name: "clearFilters" }));
    expect(replace).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("searchLabel"), { target: { value: "matrix" } });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).toHaveBeenCalledTimes(2);
    expect(replace).toHaveBeenLastCalledWith({
      pathname: "/admin/movies",
      query: { search: "matrix" },
    });
  });

  it("combines search, date range and rating ranges with genre/sort in one navigation", async () => {
    vi.useFakeTimers();
    render(
      <AdminCatalogFilters
        type="book"
        genres={genres}
        selectedGenre="drama"
        selectedSort="title_asc"
      />,
    );
    await openMoreFilters();

    fireEvent.change(screen.getByLabelText("searchLabel"), { target: { value: "dune" } });
    fireEvent.change(screen.getByLabelText("dateFromLabel"), { target: { value: "2000-01-01" } });
    fireEvent.change(screen.getByLabelText("ratingExternalMinLabel"), { target: { value: "5" } });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/admin/books",
      query: {
        genre: "drama",
        sort: "title_asc",
        search: "dune",
        date_from: "2000-01-01",
        rating_external_min: "5",
      },
    });
  });
});
