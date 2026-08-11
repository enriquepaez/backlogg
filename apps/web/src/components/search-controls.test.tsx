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

describe("SearchControls", () => {
  it("does not navigate on mount", () => {
    render(<SearchControls initialQuery="dune" />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(replace).not.toHaveBeenCalled();
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
});
