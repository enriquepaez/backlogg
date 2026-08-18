import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Same rationale as `library-sort.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl`.
const replace = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { LibraryViewToggle } = await import("./library-view-toggle");

beforeEach(() => {
  replace.mockClear();
  window.localStorage.clear();
});

describe("LibraryViewToggle", () => {
  it("renders a grid and a board button, marking the current view as pressed", () => {
    render(
      <LibraryViewToggle
        username="alice"
        sort="updated_desc"
        view="grid"
        hasExplicitView={false}
      />,
    );

    expect(screen.getByRole("group", { name: "label" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /grid/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /board/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("navigates to ?view=board and persists the choice to localStorage on click", () => {
    render(
      <LibraryViewToggle
        username="alice"
        status="completed"
        type="movie"
        sort="updated_desc"
        view="grid"
        hasExplicitView={true}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /board/ }));

    expect(replace).toHaveBeenCalledWith({
      pathname: "/u/alice/library",
      query: { status: "completed", type: "movie", view: "board" },
    });
    expect(window.localStorage.getItem("backlogg:library-view:alice")).toBe("board");
  });

  it("omits view from the query when switching back to the default (grid)", () => {
    render(
      <LibraryViewToggle username="alice" sort="updated_desc" view="board" hasExplicitView={true} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /grid/ }));

    expect(replace).toHaveBeenCalledWith({ pathname: "/u/alice/library", query: {} });
    expect(window.localStorage.getItem("backlogg:library-view:alice")).toBe("grid");
  });

  it("uses a per-username localStorage key so two accounts never share a preference", () => {
    render(
      <LibraryViewToggle username="alice" sort="updated_desc" view="grid" hasExplicitView={true} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /board/ }));

    expect(window.localStorage.getItem("backlogg:library-view:alice")).toBe("board");
    expect(window.localStorage.getItem("backlogg:library-view:bob")).toBeNull();
  });

  it("redirects to the saved localStorage preference on mount when the URL has no explicit ?view=", () => {
    window.localStorage.setItem("backlogg:library-view:alice", "board");

    render(
      <LibraryViewToggle
        username="alice"
        sort="updated_desc"
        view="grid"
        hasExplicitView={false}
      />,
    );

    expect(replace).toHaveBeenCalledWith({ pathname: "/u/alice/library", query: { view: "board" } });
  });

  it("does not redirect on mount when ?view= was explicitly present in the URL", () => {
    window.localStorage.setItem("backlogg:library-view:alice", "board");

    render(
      <LibraryViewToggle username="alice" sort="updated_desc" view="grid" hasExplicitView={true} />,
    );

    expect(replace).not.toHaveBeenCalled();
  });

  it("does not redirect on mount when there is no saved preference", () => {
    render(
      <LibraryViewToggle
        username="alice"
        sort="updated_desc"
        view="grid"
        hasExplicitView={false}
      />,
    );

    expect(replace).not.toHaveBeenCalled();
  });

  it("does not redirect on mount when the saved preference already matches the resolved view", () => {
    window.localStorage.setItem("backlogg:library-view:alice", "grid");

    render(
      <LibraryViewToggle
        username="alice"
        sort="updated_desc"
        view="grid"
        hasExplicitView={false}
      />,
    );

    expect(replace).not.toHaveBeenCalled();
  });
});
