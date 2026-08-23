import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/queries/query-keys";
import { server } from "@/test/msw/server";
import { createTestQueryClient, renderWithQuery } from "@/test/render-with-query";

// Same rationale as `rating-widget.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl` — `LibraryStatusCounts` became a Client Component in FE-48
// (previously an `async` Server Component using `next-intl/server`'s
// `getTranslations`), so its test now mocks the client `useTranslations`
// hook instead of `next-intl/server`.
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

vi.mock("next-intl", () => ({
  useTranslations: (namespace: string) => (key: string) => `${namespace}.${key}`,
}));

const { LibraryStatusCounts } = await import("./library-status-counts");

afterEach(() => {
  server.resetHandlers();
});

describe("LibraryStatusCounts", () => {
  it("renders one colored link per status, in order, linking to the filtered library view", async () => {
    renderWithQuery(
      <LibraryStatusCounts
        username="alice"
        counts={{ want: 3, in_progress: 1, completed: 12, dropped: 2 }}
      />,
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
    renderWithQuery(
      <LibraryStatusCounts
        username="bob"
        counts={{ want: 0, in_progress: 0, completed: 0, dropped: 0 }}
      />,
    );

    expect(screen.getAllByRole("link")).toHaveLength(4);
    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveTextContent("0");
    }
  });

  // FE-48 acceptance: completing an item in the item detail invalidates
  // `library_counts` on the profile — this is the "receiving" half of that
  // cross-widget invalidation. `viewer-status-slot.tsx`'s own test suite
  // covers that it actually calls `invalidateQueries`; this test instead
  // proves what happens *when* that invalidated query refetches: the
  // `useQuery`'s `initialData` (the `counts` prop, seeded from the page's
  // own SSR fetch) shows immediately with no loading flash, and a refetch
  // (simulated directly via `queryClient.invalidateQueries`, the same call
  // `ViewerStatusSlot` makes) silently swaps in the fresh numbers.
  it("shows the initial counts immediately, then swaps in fresh numbers once the shared query key is invalidated", async () => {
    server.use(
      http.get("/api/users/alice/library_counts", () =>
        HttpResponse.json({ counts: { want: 3, in_progress: 1, completed: 13, dropped: 2 } }),
      ),
    );

    // Not `renderWithQuery` (its `QueryClient` is created internally, out of
    // reach) — this test needs to call `invalidateQueries` on the exact same
    // client the component reads from, the same way `ViewerStatusSlot`'s own
    // `useQueryClient()` would in the real app.
    const queryClient = createTestQueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <LibraryStatusCounts
          username="alice"
          counts={{ want: 3, in_progress: 1, completed: 12, dropped: 2 }}
        />
      </QueryClientProvider>,
    );

    // `initialData` renders the SSR-known value immediately, no fetch yet.
    const completedLink = () => screen.getByRole("link", { name: /Library\.statusTabs\.completed/ });
    expect(completedLink()).toHaveTextContent("12");

    await queryClient.invalidateQueries({ queryKey: queryKeys.library.counts.all });

    await vi.waitFor(() => expect(completedLink()).toHaveTextContent("13"));
  });
});
