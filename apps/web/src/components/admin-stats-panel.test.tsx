import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `notification-bell.test.tsx` for mocking `next-intl`:
// the translation keys/values themselves aren't under test here, only the
// component's own branching (loading/error/loaded states).
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
  useLocale: () => "en",
}));

const { AdminStatsPanel } = await import("./admin-stats-panel");

const statsFixture = {
  movies: { count: 847, last_synced_at: "2026-05-25T02:03:12Z" },
  series: { count: 312, last_synced_at: "2026-05-25T02:04:01Z" },
  books: { count: 520, last_synced_at: null },
  games: { count: 198, last_synced_at: "2026-05-25T02:06:33Z" },
};

afterEach(() => {
  server.resetHandlers();
});

describe("AdminStatsPanel", () => {
  it("shows a loading state before the fetch resolves", () => {
    server.use(http.get("/api/admin/stats", () => HttpResponse.json(statsFixture)));

    render(<AdminStatsPanel />);

    expect(screen.getByRole("status")).toHaveTextContent("loading");
  });

  it("renders per-type counts and last-synced dates on success", async () => {
    server.use(http.get("/api/admin/stats", () => HttpResponse.json(statsFixture)));

    render(<AdminStatsPanel />);

    expect(await screen.findByText("847")).toBeInTheDocument();
    expect(screen.getByText("312")).toBeInTheDocument();
    expect(screen.getByText("520")).toBeInTheDocument();
    expect(screen.getByText("198")).toBeInTheDocument();
    // `books.last_synced_at` is null -> the "never synced" copy, not the
    // dated one.
    expect(screen.getByText("lastSyncedNever")).toBeInTheDocument();
  });

  it("shows a clear, distinct message on 401 (wrong/missing key)", async () => {
    server.use(http.get("/api/admin/stats", () => new HttpResponse(null, { status: 401 })));

    render(<AdminStatsPanel />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("errors.unauthorized"));
  });

  it("shows a clear, distinct message on 503 (key not configured)", async () => {
    server.use(http.get("/api/admin/stats", () => new HttpResponse(null, { status: 503 })));

    render(<AdminStatsPanel />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("errors.not_configured"),
    );
  });

  it("shows a generic error message on an unexpected failure", async () => {
    server.use(http.get("/api/admin/stats", () => new HttpResponse(null, { status: 500 })));

    render(<AdminStatsPanel />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("errors.unknown"));
  });
});
