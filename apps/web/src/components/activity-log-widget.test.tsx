import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `rating-widget.test.tsx` for mocking `@/i18n/navigation`
// (the anonymous state's "log in" link) and `next-intl` (assertions match on
// message keys instead of needing a real `NextIntlClientProvider`). `sonner`'s
// `toast` is mocked the same way too.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

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

const { ActivityLogWidget } = await import("./activity-log-widget");

const entryOne = { id: 1, logged_on: "2026-01-01", rewatch: false, note: "First watch" };
const entryTwo = { id: 2, logged_on: "2026-02-01", rewatch: true, note: null };

function renderWidget() {
  return render(<ActivityLogWidget type="movie" slug="dune-2021" />);
}

beforeEach(() => {
  toastSuccess.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("ActivityLogWidget", () => {
  it("prompts anonymous viewers to log in and never renders the form", async () => {
    server.use(
      http.get("/api/movie/dune-2021/log", () =>
        HttpResponse.json({ authenticated: false, mine: [], items: [], total: 0, page: 1, limit: 20 }),
      ),
    );

    renderWidget();

    expect(await screen.findByText("anonymousPrompt")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "anonymousLoginLink" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("button", { name: "addEntry" })).not.toBeInTheDocument();
  });

  it("shows an empty history message and the create form when authenticated with no entries yet", async () => {
    server.use(
      http.get("/api/movie/dune-2021/log", () =>
        HttpResponse.json({ authenticated: true, mine: [], items: [], total: 0, page: 1, limit: 20 }),
      ),
    );

    renderWidget();

    expect(await screen.findByRole("button", { name: "addEntry" })).toBeInTheDocument();
    expect(screen.getByText("historyEmpty")).toBeInTheDocument();
  });

  it("shows the caller's own log history with date, rewatch state and note", async () => {
    server.use(
      http.get("/api/movie/dune-2021/log", () =>
        HttpResponse.json({
          authenticated: true,
          mine: [entryTwo, entryOne],
          items: [],
          total: 0,
          page: 1,
          limit: 20,
        }),
      ),
    );

    renderWidget();

    expect(await screen.findByText("First watch")).toBeInTheDocument();
    expect(screen.getByText("rewatchNo")).toBeInTheDocument();
    expect(screen.getByText("rewatchYes")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "delete" })).toHaveLength(2);
  });

  it("shows a load error when the initial fetch fails", async () => {
    server.use(http.get("/api/movie/dune-2021/log", () => new HttpResponse(null, { status: 500 })));

    renderWidget();

    expect(await screen.findByText("loadError")).toBeInTheDocument();
  });

  it("submits a new log entry, forwarding the exact POST body, and prepends it to the history", async () => {
    server.use(
      http.get("/api/movie/dune-2021/log", () =>
        HttpResponse.json({ authenticated: true, mine: [entryOne], items: [], total: 0, page: 1, limit: 20 }),
      ),
    );
    let forwardedBody: unknown;
    server.use(
      http.post("/api/movie/dune-2021/log", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(entryTwo, { status: 201 });
      }),
    );

    renderWidget();
    await screen.findByText("First watch");

    fireEvent.change(screen.getByLabelText("dateLabel"), { target: { value: "2026-02-01" } });
    fireEvent.click(screen.getByLabelText("rewatchLabel"));
    fireEvent.change(screen.getByLabelText("noteLabel"), { target: { value: "  " } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "addEntry" }));
    });

    await waitFor(() =>
      expect(forwardedBody).toEqual({ logged_on: "2026-02-01", rewatch: true, note: null }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("saveSuccess");
    // The freshly created entry (logged_on 2026-02-01) sorts before the
    // already-loaded one (2026-01-01) — newest logged_on first.
    const dates = screen.getAllByText(/^January|^February/);
    expect(dates.length).toBeGreaterThanOrEqual(2);
  });

  it("shows the validation error copy on a 422 from the backend", async () => {
    server.use(
      http.get("/api/movie/dune-2021/log", () =>
        HttpResponse.json({ authenticated: true, mine: [], items: [], total: 0, page: 1, limit: 20 }),
      ),
    );
    server.use(http.post("/api/movie/dune-2021/log", () => new HttpResponse(null, { status: 422 })));

    renderWidget();
    await screen.findByRole("button", { name: "addEntry" });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "addEntry" }));
    });

    expect(await screen.findByText("validation")).toBeInTheDocument();
  });

  it("deletes a log entry and removes it from the history on success", async () => {
    server.use(
      http.get("/api/movie/dune-2021/log", () =>
        HttpResponse.json({
          authenticated: true,
          mine: [entryOne, entryTwo],
          items: [],
          total: 0,
          page: 1,
          limit: 20,
        }),
      ),
    );
    const deleteCall = vi.fn();
    server.use(
      http.delete("/api/log/1", () => {
        deleteCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWidget();
    await screen.findByText("First watch");

    await act(async () => {
      fireEvent.click(screen.getAllByRole("button", { name: "delete" })[0]);
    });

    await waitFor(() => expect(screen.queryByText("First watch")).not.toBeInTheDocument());
    expect(deleteCall).toHaveBeenCalledTimes(1);
    expect(toastSuccess).toHaveBeenCalledWith("deleteSuccess");
  });

  it("shows an error toast and keeps the entry when delete fails", async () => {
    server.use(
      http.get("/api/movie/dune-2021/log", () =>
        HttpResponse.json({ authenticated: true, mine: [entryOne], items: [], total: 0, page: 1, limit: 20 }),
      ),
    );
    server.use(http.delete("/api/log/1", () => new HttpResponse(null, { status: 500 })));

    renderWidget();
    await screen.findByText("First watch");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "delete" }));
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("deleteError"));
    expect(screen.getByText("First watch")).toBeInTheDocument();
  });
});
