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

const { LibrarySortSelect } = await import("./library-sort");

beforeEach(() => {
  replace.mockClear();
});

describe("LibrarySortSelect", () => {
  it("renders one option per sort value", () => {
    render(<LibrarySortSelect username="alice" selectedSort="updated_desc" />);

    const select = screen.getByLabelText("label");
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.value)).toEqual([
      "updated_desc",
      "rating_desc",
      "title_asc",
      "date_desc",
    ]);
  });

  it("navigates with the selected sort, resetting page and preserving status/type", () => {
    render(
      <LibrarySortSelect username="alice" status="completed" type="movie" selectedSort="updated_desc" />,
    );

    fireEvent.change(screen.getByLabelText("label"), { target: { value: "title_asc" } });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/u/alice/library",
      query: { status: "completed", type: "movie", sort: "title_asc" },
    });
  });

  it("omits sort from the query when it's the default (updated_desc)", () => {
    render(<LibrarySortSelect username="alice" selectedSort="title_asc" />);

    fireEvent.change(screen.getByLabelText("label"), { target: { value: "updated_desc" } });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/u/alice/library",
      query: {},
    });
  });

  it("omits status/type from the query when unset", () => {
    render(<LibrarySortSelect username="alice" selectedSort="updated_desc" />);

    fireEvent.change(screen.getByLabelText("label"), { target: { value: "rating_desc" } });

    expect(replace).toHaveBeenCalledWith({
      pathname: "/u/alice/library",
      query: { sort: "rating_desc" },
    });
  });
});
