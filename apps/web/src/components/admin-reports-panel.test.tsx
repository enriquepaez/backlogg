import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `admin-stats-panel.test.tsx`/`item-reviews.test.tsx` for
// mocking `next-intl`: only this component's own branching (filter/loading/
// error/loaded/resolve) is under test, not the translated copy itself.
// Interpolated keys (`t(key, vars)`) serialize as `key:{"var":"value"}` so
// assertions can match on both the key and the values passed to it.
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
  useLocale: () => "en",
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const { AdminReportsPanel } = await import("./admin-reports-panel");

const openReport = {
  id: 1,
  reporter_id: 10,
  rating_id: 42,
  reason: "Spam content",
  status: "open",
  created_at: "2026-05-25T02:03:12Z",
  resolved_at: null,
};

const resolvedReport = {
  id: 2,
  reporter_id: 11,
  rating_id: 43,
  reason: null,
  status: "resolved",
  created_at: "2026-05-20T02:03:12Z",
  resolved_at: "2026-05-21T02:03:12Z",
};

function reportsHandler(items: unknown[], overrides: Record<string, unknown> = {}) {
  return http.get("/api/admin/reports", () =>
    HttpResponse.json({ items, total: items.length, page: 1, limit: 20, ...overrides }),
  );
}

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
  toastSuccess.mockClear();
  toastError.mockClear();
});

describe("AdminReportsPanel", () => {
  it("shows a loading state before the fetch resolves", () => {
    server.use(reportsHandler([]));

    render(<AdminReportsPanel />);

    expect(screen.getByRole("status")).toHaveTextContent("loading");
  });

  it("shows an empty state when there are no reports", async () => {
    server.use(reportsHandler([]));

    render(<AdminReportsPanel />);

    expect(await screen.findByText("empty")).toBeInTheDocument();
  });

  it("renders report fields: rating id, reason, status and dates", async () => {
    server.use(reportsHandler([openReport]));

    render(<AdminReportsPanel />);

    expect(await screen.findByText('reviewLabel:{"ratingId":42}')).toBeInTheDocument();
    expect(screen.getByText("Spam content")).toBeInTheDocument();
    expect(screen.getByText("status.open")).toBeInTheDocument();
    expect(
      screen.getByText('createdAtLabel:{"date":"May 25, 2026"}'),
    ).toBeInTheDocument();
  });

  it("shows the no-reason copy when reason is null", async () => {
    server.use(reportsHandler([resolvedReport]));

    render(<AdminReportsPanel />);

    expect(await screen.findByText("noReason")).toBeInTheDocument();
  });

  it("shows resolvedAt only for resolved reports and hides the resolve button", async () => {
    server.use(reportsHandler([resolvedReport]));

    render(<AdminReportsPanel />);

    expect(
      await screen.findByText('resolvedAtLabel:{"date":"May 21, 2026"}'),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "resolveAction" })).not.toBeInTheDocument();
  });

  it("shows a clear, distinct message on 401 (wrong/missing key)", async () => {
    server.use(http.get("/api/admin/reports", () => new HttpResponse(null, { status: 401 })));

    render(<AdminReportsPanel />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("errors.unauthorized"));
  });

  it("shows a clear, distinct message on 503 (key not configured)", async () => {
    server.use(http.get("/api/admin/reports", () => new HttpResponse(null, { status: 503 })));

    render(<AdminReportsPanel />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("errors.not_configured"),
    );
  });

  it("shows a generic error message on an unexpected failure", async () => {
    server.use(http.get("/api/admin/reports", () => new HttpResponse(null, { status: 500 })));

    render(<AdminReportsPanel />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("errors.unknown"));
  });

  it("filters by status: switching tabs forwards ?status= and refetches", async () => {
    let forwardedStatus: string | null = "not-called";
    server.use(
      http.get("/api/admin/reports", ({ request }) => {
        forwardedStatus = new URL(request.url).searchParams.get("status");
        return HttpResponse.json({ items: [openReport], total: 1, page: 1, limit: 20 });
      }),
    );

    render(<AdminReportsPanel />);
    await screen.findByText('reviewLabel:{"ratingId":42}');
    expect(forwardedStatus).toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByRole("tab", { name: "filters.open" }));
    });

    await waitFor(() => expect(forwardedStatus).toBe("open"));
  });

  it("resolves an open report: posts to /api/admin/reports/{id}/resolve and refreshes the queue", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/admin/reports", () => {
        callCount += 1;
        const items = callCount === 1 ? [openReport] : [{ ...openReport, status: "resolved" }];
        return HttpResponse.json({ items, total: 1, page: 1, limit: 20 });
      }),
    );
    let resolvedId: string | undefined;
    server.use(
      http.post("/api/admin/reports/:id/resolve", ({ params }) => {
        resolvedId = params.id as string;
        return HttpResponse.json({ ...openReport, status: "resolved" });
      }),
    );

    render(<AdminReportsPanel />);
    const resolveButton = await screen.findByRole("button", { name: "resolveAction" });

    await act(async () => {
      fireEvent.click(resolveButton);
    });

    expect(resolvedId).toBe("1");
    expect(toastSuccess).toHaveBeenCalledWith("resolveSuccess");
    await waitFor(() => expect(callCount).toBe(2));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "resolveAction" })).not.toBeInTheDocument(),
    );
  });

  it("shows an error toast and keeps the report open when resolve fails", async () => {
    server.use(reportsHandler([openReport]));
    server.use(
      http.post("/api/admin/reports/:id/resolve", () => new HttpResponse(null, { status: 500 })),
    );

    render(<AdminReportsPanel />);
    const resolveButton = await screen.findByRole("button", { name: "resolveAction" });

    await act(async () => {
      fireEvent.click(resolveButton);
    });

    expect(toastError).toHaveBeenCalledWith("resolveError");
    expect(screen.getByRole("button", { name: "resolveAction" })).toBeInTheDocument();
  });

  it("hides a review: posts to /api/admin/reviews/{ratingId}/hide and shows the hidden badge", async () => {
    server.use(reportsHandler([openReport]));
    let hiddenRatingId: string | undefined;
    server.use(
      http.post("/api/admin/reviews/:id/hide", ({ params }) => {
        hiddenRatingId = params.id as string;
        return HttpResponse.json({ id: 42, is_hidden: true });
      }),
    );

    render(<AdminReportsPanel />);
    const hideButton = await screen.findByRole("button", { name: "hideAction" });

    await act(async () => {
      fireEvent.click(hideButton);
    });

    expect(hiddenRatingId).toBe("42");
    expect(toastSuccess).toHaveBeenCalledWith("hideSuccess");
    expect(await screen.findByText("reviewHidden")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "unhideAction" })).toBeInTheDocument();
  });

  it("unhides a review after it was hidden: posts to /api/admin/reviews/{ratingId}/unhide", async () => {
    server.use(reportsHandler([openReport]));
    server.use(
      http.post("/api/admin/reviews/:id/hide", () => HttpResponse.json({ id: 42, is_hidden: true })),
    );
    let unhiddenRatingId: string | undefined;
    server.use(
      http.post("/api/admin/reviews/:id/unhide", ({ params }) => {
        unhiddenRatingId = params.id as string;
        return HttpResponse.json({ id: 42, is_hidden: false });
      }),
    );

    render(<AdminReportsPanel />);
    const hideButton = await screen.findByRole("button", { name: "hideAction" });
    await act(async () => {
      fireEvent.click(hideButton);
    });
    const unhideButton = await screen.findByRole("button", { name: "unhideAction" });

    await act(async () => {
      fireEvent.click(unhideButton);
    });

    expect(unhiddenRatingId).toBe("42");
    expect(toastSuccess).toHaveBeenCalledWith("unhideSuccess");
    expect(await screen.findByText("reviewVisible")).toBeInTheDocument();
  });

  it("shows an error toast and keeps the previous hide/unhide label when the toggle fails", async () => {
    server.use(reportsHandler([openReport]));
    server.use(http.post("/api/admin/reviews/:id/hide", () => new HttpResponse(null, { status: 500 })));

    render(<AdminReportsPanel />);
    const hideButton = await screen.findByRole("button", { name: "hideAction" });

    await act(async () => {
      fireEvent.click(hideButton);
    });

    expect(toastError).toHaveBeenCalledWith("hideError");
    expect(screen.getByRole("button", { name: "hideAction" })).toBeInTheDocument();
    expect(screen.queryByText("reviewHidden")).not.toBeInTheDocument();
  });

  it("paginates: next/previous forward the right ?page= to the BFF route", async () => {
    let forwardedPage: string | null = null;
    server.use(
      http.get("/api/admin/reports", ({ request }) => {
        forwardedPage = new URL(request.url).searchParams.get("page");
        return HttpResponse.json({ items: [openReport], total: 41, page: 1, limit: 20 });
      }),
    );

    render(<AdminReportsPanel />);
    await screen.findByText('reviewLabel:{"ratingId":42}');
    expect(forwardedPage).toBe("1");

    const nextButton = screen.getByRole("button", { name: "pagination.next" });
    await act(async () => {
      fireEvent.click(nextButton);
    });

    await waitFor(() => expect(forwardedPage).toBe("2"));
  });
});
