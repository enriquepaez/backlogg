import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `library-pagination.test.tsx`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({
    href,
    children,
    ...props
  }: {
    href: string | object;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : JSON.stringify(href)} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => (key: string) => `${namespace}.${key}`,
}));

// `LibraryStatusCounts` is a Server Component (async function returning
// JSX) — called directly and awaited, same pattern as
// `library-pagination.test.tsx`.
const { LibraryStatusCounts } = await import("./library-status-counts");

describe("LibraryStatusCounts", () => {
  it("renders one colored link per status, in order, linking to the filtered library view", async () => {
    render(
      await LibraryStatusCounts({
        username: "alice",
        counts: { want: 3, in_progress: 1, completed: 12, dropped: 2 },
      }),
    );

    const group = screen.getByRole("group", { name: "Profile.library.countsLabel" });
    const links = screen.getAllByRole("link");
    expect(group).toContainElement(links[0]);
    expect(links).toHaveLength(4);

    const expected: Array<{ status: string; count: number }> = [
      { status: "want", count: 3 },
      { status: "in_progress", count: 1 },
      { status: "completed", count: 12 },
      { status: "dropped", count: 2 },
    ];
    expected.forEach(({ status, count }, index) => {
      const link = links[index];
      expect(link).toHaveAttribute(
        "href",
        JSON.stringify({ pathname: "/u/alice/library", query: { status } }),
      );
      expect(link).toHaveTextContent(String(count));
      expect(link).toHaveTextContent(`Library.statusTabs.${status}`);
      expect(link.className).toContain(`bg-status-${status.replace("_", "-")}`);
    });
  });

  it("renders zero counts as-is (no hidden/omitted statuses)", async () => {
    render(
      await LibraryStatusCounts({
        username: "bob",
        counts: { want: 0, in_progress: 0, completed: 0, dropped: 0 },
      }),
    );

    expect(screen.getAllByRole("link")).toHaveLength(4);
    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveTextContent("0");
    }
  });
});
