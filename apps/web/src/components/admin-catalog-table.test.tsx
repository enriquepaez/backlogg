import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
}));

// `AdminCatalogEditDialog` has its own dedicated test — stubbed here as a
// simple control surface exposing `onSaved`/`onClose` via buttons, same
// rationale `admin-user-actions-panel.test.tsx` uses for not re-testing a
// child's internals from its parent's test file.
type DialogProps = {
  type: string;
  slug: string;
  fallbackTitle: string;
  dateLabel: string;
  onClose: () => void;
  onSaved: (item: unknown) => void;
};
vi.mock("./admin-catalog-edit-dialog", () => ({
  AdminCatalogEditDialog: ({ slug, fallbackTitle, onClose, onSaved }: DialogProps) => (
    <div data-testid="edit-dialog" data-slug={slug} data-fallback-title={fallbackTitle}>
      <button type="button" onClick={onClose}>
        close-dialog
      </button>
      <button
        type="button"
        onClick={() =>
          onSaved({
            type: "movie",
            slug,
            title: "Dune (Updated)",
            poster_url: "https://example.com/new.jpg",
            release_date: "2021-11-01",
            first_air_date: null,
            first_publish_date: null,
            genres: ["Sci-Fi Epic"],
            locked_fields: ["title"],
          })
        }
      >
        save-dialog
      </button>
    </div>
  ),
}));

const { AdminCatalogTable } = await import("./admin-catalog-table");

const items = [
  {
    id: 1,
    title: "Dune",
    slug: "dune-2021",
    poster_url: null,
    release_date: "2021-10-22",
    rating_external: 7.8,
    genres: ["science-fiction"],
  },
  {
    id: 2,
    title: "Untitled",
    slug: "untitled",
    poster_url: null,
    release_date: null,
    rating_external: null,
    genres: [],
  },
];

describe("AdminCatalogTable — rows", () => {
  it("renders a real <table> with title, genres, date and rating per row", () => {
    render(<AdminCatalogTable type="movie" items={items} dateLabel="Release date" />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Dune")).toBeInTheDocument();
    expect(screen.getByText("science-fiction")).toBeInTheDocument();
    expect(screen.getByText("2021-10-22")).toBeInTheDocument();
    expect(screen.getByText("7.8")).toBeInTheDocument();
    expect(screen.getByText("Release date")).toBeInTheDocument();
  });

  it("shows a placeholder for missing genres/date/rating", () => {
    render(<AdminCatalogTable type="movie" items={items} dateLabel="Release date" />);

    // "Untitled" row: no genres, no date, no rating -> 3 placeholders.
    expect(screen.getAllByText("emptyValue")).toHaveLength(3);
  });

  it("does not render the edit dialog until a row's edit action is clicked", () => {
    render(<AdminCatalogTable type="movie" items={items} dateLabel="Release date" />);

    expect(screen.queryByTestId("edit-dialog")).not.toBeInTheDocument();
  });

  it("opens the edit dialog for the clicked row's slug", async () => {
    render(<AdminCatalogTable type="movie" items={items} dateLabel="Release date" />);

    const editButtons = screen.getAllByRole("button", { name: "editAction" });
    await act(async () => {
      fireEvent.click(editButtons[0]);
    });

    const dialog = screen.getByTestId("edit-dialog");
    expect(dialog).toHaveAttribute("data-slug", "dune-2021");
    expect(dialog).toHaveAttribute("data-fallback-title", "Dune");
  });

  it("closes the dialog via onClose", async () => {
    render(<AdminCatalogTable type="movie" items={items} dateLabel="Release date" />);

    await act(async () => {
      fireEvent.click(screen.getAllByRole("button", { name: "editAction" })[0]);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "close-dialog" }));
    });

    expect(screen.queryByTestId("edit-dialog")).not.toBeInTheDocument();
  });

  it("refreshes the row's displayed fields with the dialog's onSaved result and closes it", async () => {
    render(<AdminCatalogTable type="movie" items={items} dateLabel="Release date" />);

    await act(async () => {
      fireEvent.click(screen.getAllByRole("button", { name: "editAction" })[0]);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save-dialog" }));
    });

    expect(screen.queryByTestId("edit-dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Dune (Updated)")).toBeInTheDocument();
    expect(screen.getByText("2021-11-01")).toBeInTheDocument();
    expect(screen.getByText("Sci-Fi Epic")).toBeInTheDocument();
  });
});
