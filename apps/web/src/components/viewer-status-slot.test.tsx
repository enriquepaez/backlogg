import { act } from "react";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";
import { renderWithQuery } from "@/test/render-with-query";
import { LIBRARY_STATUSES, STATUS_COLOR_CLASSES_IMPORTANT } from "@/lib/library-types";

// Same rationale as `rating-widget.test.tsx` for mocking `@/i18n/navigation`
// (the anonymous state's "log in" link), `next-intl` (assertions match on
// message keys instead of needing a real `NextIntlClientProvider`), and
// `sonner`'s `toast`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const { ViewerStatusSlot } = await import("./viewer-status-slot");

function renderSlot(status: string | null = null) {
  return renderWithQuery(<ViewerStatusSlot status={status} type="movie" slug="dune-2021" />);
}

async function statusGroup() {
  return within(await screen.findByRole("group", { name: "heading" }));
}

beforeEach(() => {
  toastError.mockClear();
});

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("ViewerStatusSlot", () => {
  it("prompts anonymous viewers to log in and never renders the status controls", async () => {
    server.use(
      http.get("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ authenticated: false, status: null }),
      ),
    );

    renderSlot();

    expect(await screen.findByText("anonymousPrompt")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "anonymousLoginLink" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("group", { name: "heading" })).not.toBeInTheDocument();
  });

  it("renders the four status options with none selected and no remove action when the viewer has no entry", async () => {
    server.use(
      http.get("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ authenticated: true, status: null }),
      ),
    );

    renderSlot();

    const buttons = await (await statusGroup()).findAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "status.want",
      "status.in_progress",
      "status.completed",
      "status.dropped",
    ]);
    buttons.forEach((button) => expect(button).toHaveAttribute("aria-pressed", "false"));
    expect(screen.queryByRole("button", { name: "remove" })).not.toBeInTheDocument();
  });

  it("marks the viewer's current status as pressed and shows the remove action", async () => {
    server.use(
      http.get("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ authenticated: true, status: "in_progress" }),
      ),
    );

    renderSlot();

    const pressed = await screen.findByRole("button", { name: "status.in_progress" });
    expect(pressed).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "remove" })).toBeInTheDocument();
  });

  it.each(LIBRARY_STATUSES)(
    "gives the active '%s' status button its own `!important` status color, distinct from the others (FE-37)",
    async (activeStatus) => {
      // `!`-prefixed classes (`STATUS_COLOR_CLASSES_IMPORTANT`, not the plain
      // `STATUS_COLOR_CLASSES`) — this button uses `variant="outline"`, whose
      // `dark:*` rules otherwise win the cascade over the status color in
      // dark theme (FE-37 bugfix, see the doc comment on
      // `STATUS_COLOR_CLASSES_IMPORTANT`).
      server.use(
        http.get("/api/movie/dune-2021/library", () =>
          HttpResponse.json({ authenticated: true, status: activeStatus }),
        ),
      );

      renderSlot();

      const activeButton = await screen.findByRole("button", { name: `status.${activeStatus}` });
      expect(activeButton).toHaveClass("!border-transparent");
      for (const className of STATUS_COLOR_CLASSES_IMPORTANT[activeStatus].split(" ")) {
        expect(activeButton).toHaveClass(className);
      }

      for (const otherStatus of LIBRARY_STATUSES.filter((value) => value !== activeStatus)) {
        const inactiveButton = screen.getByRole("button", { name: `status.${otherStatus}` });
        for (const className of STATUS_COLOR_CLASSES_IMPORTANT[otherStatus].split(" ")) {
          expect(inactiveButton).not.toHaveClass(className);
        }
      }
    },
  );

  it("sets a new status with an optimistic update, forwarding the exact PUT body", async () => {
    server.use(
      http.get("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ authenticated: true, status: null }),
      ),
    );
    let forwardedBody: unknown;
    server.use(
      http.put("/api/movie/dune-2021/library", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ item_type: "MOVIE", slug: "dune-2021", status: "want", created_at: "t", updated_at: "t" });
      }),
    );

    renderSlot();
    await (await statusGroup()).findAllByRole("button");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "status.want" }));
    });

    await waitFor(() => expect(forwardedBody).toEqual({ status: "want" }));
    expect(screen.getByRole("button", { name: "status.want" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "remove" })).toBeInTheDocument();
  });

  it("changing status swaps which button is pressed", async () => {
    server.use(
      http.get("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ authenticated: true, status: "want" }),
      ),
    );
    server.use(
      http.put("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ item_type: "MOVIE", slug: "dune-2021", status: "completed", created_at: "t", updated_at: "t" }),
      ),
    );

    renderSlot();
    await screen.findByRole("button", { name: "status.want" });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "status.completed" }));
    });

    expect(screen.getByRole("button", { name: "status.completed" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "status.want" })).toHaveAttribute("aria-pressed", "false");
  });

  it("removes the current status and hides the remove action", async () => {
    server.use(
      http.get("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ authenticated: true, status: "completed" }),
      ),
    );
    const deleteCall = vi.fn();
    server.use(
      http.delete("/api/movie/dune-2021/library", () => {
        deleteCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderSlot();
    await screen.findByRole("button", { name: "remove" });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "remove" }));
    });

    expect(deleteCall).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("button", { name: "remove" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "status.completed" })).toHaveAttribute("aria-pressed", "false");
  });

  it("rolls back and toasts an error when a status change fails", async () => {
    server.use(
      http.get("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ authenticated: true, status: null }),
      ),
    );
    server.use(http.put("/api/movie/dune-2021/library", () => new HttpResponse(null, { status: 401 })));

    renderSlot();
    await (await statusGroup()).findAllByRole("button");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "status.want" }));
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("error"));
    expect(screen.getByRole("button", { name: "status.want" })).toHaveAttribute("aria-pressed", "false");
  });

  it("ignores a second click while a mutation is still pending (no double-submit)", async () => {
    server.use(
      http.get("/api/movie/dune-2021/library", () =>
        HttpResponse.json({ authenticated: true, status: null }),
      ),
    );
    let putCalls = 0;
    server.use(
      http.put("/api/movie/dune-2021/library", async () => {
        putCalls += 1;
        await new Promise((resolve) => setTimeout(resolve, 20));
        return HttpResponse.json({ item_type: "MOVIE", slug: "dune-2021", status: "want", created_at: "t", updated_at: "t" });
      }),
    );

    renderSlot();
    await (await statusGroup()).findAllByRole("button");

    fireEvent.click(screen.getByRole("button", { name: "status.want" }));
    fireEvent.click(screen.getByRole("button", { name: "status.want" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "status.want" })).not.toBeDisabled());
    expect(putCalls).toBe(1);
  });

  it("degrades quietly to an empty ready state when the initial load fails", async () => {
    server.use(http.get("/api/movie/dune-2021/library", () => new HttpResponse(null, { status: 500 })));

    renderSlot();

    const buttons = await (await statusGroup()).findAllByRole("button");
    buttons.forEach((button) => expect(button).toHaveAttribute("aria-pressed", "false"));
    expect(screen.queryByRole("button", { name: "remove" })).not.toBeInTheDocument();
  });
});
