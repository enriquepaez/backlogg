import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LibraryEntry, LibraryStatusValue } from "@/lib/library-types";

// Same rationale as `library-status-counts.test.tsx` (both are Server
// Components that call `getTranslations` directly).
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => (key: string) => `${namespace}.${key}`,
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => <a href={href} {...props} />,
}));

const { LibraryBoard } = await import("./library-board");

function entry(itemType: string, slug: string, title: string): LibraryEntry {
  return {
    item: {
      item_type: itemType,
      slug,
      title,
      poster_url: null,
      release_date: null,
      rating_external: null,
    },
    status: "want",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as LibraryEntry;
}

const emptyColumns: Record<LibraryStatusValue, LibraryEntry[]> = {
  want: [],
  in_progress: [],
  completed: [],
  dropped: [],
};

const emptyCounts: Record<LibraryStatusValue, number> = {
  want: 0,
  in_progress: 0,
  completed: 0,
  dropped: 0,
};

describe("LibraryBoard", () => {
  it("renders one column per status, in order, with the count from countsByStatus", async () => {
    render(
      await LibraryBoard({
        entriesByStatus: emptyColumns,
        countsByStatus: { want: 3, in_progress: 1, completed: 12, dropped: 0 },
      }),
    );

    const expected: Array<{ status: string; count: string }> = [
      { status: "Library.statusTabs.want", count: "3" },
      { status: "Library.statusTabs.in_progress", count: "1" },
      { status: "Library.statusTabs.completed", count: "12" },
      { status: "Library.statusTabs.dropped", count: "0" },
    ];
    const headings = screen.getAllByText(/Library\.statusTabs\./);
    expect(headings).toHaveLength(4);
    expected.forEach(({ status, count }, index) => {
      expect(headings[index]).toHaveTextContent(status);
      expect(headings[index].parentElement).toHaveTextContent(count);
    });
  });

  it("colors each column header with the FE-37 status token", async () => {
    render(
      await LibraryBoard({ entriesByStatus: emptyColumns, countsByStatus: emptyCounts }),
    );

    const header = screen.getByText("Library.statusTabs.in_progress").parentElement;
    expect(header?.className).toContain("bg-status-in-progress");
  });

  it("renders a card per entry in each column, linking to the item detail page", async () => {
    const columns: Record<LibraryStatusValue, LibraryEntry[]> = {
      ...emptyColumns,
      want: [entry("movie", "dune-2021", "Dune"), entry("book", "hyperion", "Hyperion")],
    };

    render(await LibraryBoard({ entriesByStatus: columns, countsByStatus: emptyCounts }));

    // `name` matches loosely: `posterUrl: null` renders an accessible
    // placeholder (`role="img" aria-label={title}`, same as `CatalogCard`)
    // *inside* the link alongside the visible title text, so the link's
    // full accessible name is "Dune Dune", not just "Dune".
    expect(screen.getByRole("link", { name: /Dune/ })).toHaveAttribute("href", "/movie/dune-2021");
    expect(screen.getByRole("link", { name: /Hyperion/ })).toHaveAttribute(
      "href",
      "/book/hyperion",
    );
  });

  it("shows an empty-column message for a status with no entries", async () => {
    render(
      await LibraryBoard({ entriesByStatus: emptyColumns, countsByStatus: emptyCounts }),
    );

    expect(screen.getAllByText("Library.board.columnEmpty")).toHaveLength(4);
  });
});
