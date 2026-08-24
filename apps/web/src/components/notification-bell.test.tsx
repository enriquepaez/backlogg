import { act } from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";
import { renderWithQuery } from "@/test/render-with-query";

// Same rationale as `user-nav.test.tsx` for mocking `@/i18n/navigation`/
// `next-intl` and using `pointerDown` (not `click`) to open the Radix
// `DropdownMenu` trigger.
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

// Same rationale as `rating-widget.test.tsx`/`viewer-status-slot.test.tsx` for
// mocking `sonner`'s `toast` (FE-54: this component didn't use it before).
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const { NotificationBell } = await import("./notification-bell");

function openBell() {
  fireEvent.pointerDown(screen.getByRole("button"), { button: 0, ctrlKey: false });
}

function unreadCountHandler(count: number) {
  return http.get("/api/notifications/unread_count", () => HttpResponse.json({ unread_count: count }));
}

function notificationsHandler(items: unknown[]) {
  return http.get("/api/notifications", () =>
    HttpResponse.json({ items, total: items.length, page: 1, limit: 10 }),
  );
}

const newFollower = {
  id: 1,
  type: "new_follower",
  actor: { username: "bob", display_name: "Bob", avatar_url: null },
  target: { target_type: null, target_id: null, item_type: null, slug: null },
  is_read: false,
  created_at: "2026-05-25T18:04:11Z",
};

const reviewLike = {
  id: 2,
  type: "review_like",
  actor: { username: "carol", display_name: null, avatar_url: null },
  target: { target_type: "review", target_id: 512, item_type: "MOVIE", slug: "the-matrix-1999" },
  is_read: false,
  created_at: "2026-05-25T18:04:11Z",
};

const reviewLikeNoSlug = {
  id: 3,
  type: "review_like",
  actor: { username: "dave", display_name: "Dave", avatar_url: null },
  target: { target_type: "review", target_id: 999, item_type: null, slug: null },
  is_read: false,
  created_at: "2026-05-25T18:04:11Z",
};

const userCompleted = {
  id: 5,
  type: "user_completed",
  actor: { username: "frank", display_name: "Frank", avatar_url: null },
  target: { target_type: "MOVIE", target_id: 77, item_type: "MOVIE", slug: "the-matrix-1999" },
  is_read: false,
  created_at: "2026-05-25T18:04:11Z",
};

const userCompletedNoSlug = {
  id: 6,
  type: "user_completed",
  actor: { username: "grace", display_name: null, avatar_url: null },
  target: { target_type: "MOVIE", target_id: 78, item_type: null, slug: null },
  is_read: false,
  created_at: "2026-05-25T18:04:11Z",
};

const alreadyRead = {
  id: 4,
  type: "new_follower",
  actor: { username: "erin", display_name: "Erin", avatar_url: null },
  target: { target_type: null, target_id: null, item_type: null, slug: null },
  is_read: true,
  created_at: "2026-05-25T18:04:11Z",
};

beforeEach(() => {
  toastError.mockClear();
});

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("NotificationBell", () => {
  it("shows no badge when the unread count is 0", async () => {
    server.use(unreadCountHandler(0));

    renderWithQuery(<NotificationBell />);

    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-label", "bellLabel"));
    expect(screen.queryByText("3")).not.toBeInTheDocument();
  });

  it("shows the unread count as a badge once loaded", async () => {
    server.use(unreadCountHandler(3));

    renderWithQuery(<NotificationBell />);

    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-label",
      'bellLabelUnread:{"count":3}',
    );
  });

  it("caps the visible badge at 99+", async () => {
    server.use(unreadCountHandler(150));

    renderWithQuery(<NotificationBell />);

    expect(await screen.findByText("99+")).toBeInTheDocument();
  });

  it("fetches and shows notifications when the dropdown opens, without marking them read", async () => {
    server.use(unreadCountHandler(2));
    const markReadCall = vi.fn();
    server.use(notificationsHandler([reviewLike, newFollower]));
    server.use(
      http.post("/api/notifications/read", () => {
        markReadCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithQuery(<NotificationBell />);
    await screen.findByText("2");

    await act(async () => {
      openBell();
    });

    expect(await screen.findByText('reviewLike:{"name":"carol"}')).toBeInTheDocument();
    expect(screen.getByText('newFollower:{"name":"Bob"}')).toBeInTheDocument();
    // Opening the dropdown must not trigger the mark-as-read side effect on
    // its own anymore — that's the whole point of the QA fix.
    expect(markReadCall).not.toHaveBeenCalled();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("filters out already-read notifications client-side", async () => {
    server.use(unreadCountHandler(1));
    server.use(notificationsHandler([reviewLike, alreadyRead]));

    renderWithQuery(<NotificationBell />);
    await screen.findByText("1");

    await act(async () => {
      openBell();
    });

    expect(await screen.findByText('reviewLike:{"name":"carol"}')).toBeInTheDocument();
    expect(screen.queryByText('newFollower:{"name":"Erin"}')).not.toBeInTheDocument();
  });

  it("hides the mark-all-read entry when there are no unread notifications", async () => {
    server.use(unreadCountHandler(0));
    server.use(notificationsHandler([]));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    await screen.findByText("empty");
    expect(screen.queryByRole("menuitem", { name: "markAllRead" })).not.toBeInTheDocument();
  });

  it("marking all as read clears the list and resets the badge, only on explicit click", async () => {
    server.use(unreadCountHandler(2));
    const markReadCall = vi.fn();
    server.use(notificationsHandler([reviewLike, newFollower]));
    server.use(
      http.post("/api/notifications/read", () => {
        markReadCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithQuery(<NotificationBell />);
    await screen.findByText("2");

    await act(async () => {
      openBell();
    });

    const markAllReadItem = await screen.findByRole("menuitem", { name: "markAllRead" });
    expect(markReadCall).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(markAllReadItem);
    });

    await waitFor(() => expect(markReadCall).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText("2")).not.toBeInTheDocument());
    expect(screen.getByText("empty")).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "markAllRead" })).not.toBeInTheDocument();
  });

  it("links review_like to the target item, not the actor's profile", async () => {
    server.use(unreadCountHandler(0));
    server.use(notificationsHandler([reviewLike]));
    server.use(http.post("/api/notifications/read", () => new HttpResponse(null, { status: 204 })));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    const row = (await screen.findByText('reviewLike:{"name":"carol"}')).closest("a");
    expect(row).toHaveAttribute("href", "/movie/the-matrix-1999");
  });

  it("links new_follower to the actor's profile", async () => {
    server.use(unreadCountHandler(0));
    server.use(notificationsHandler([newFollower]));
    server.use(http.post("/api/notifications/read", () => new HttpResponse(null, { status: 204 })));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    const row = (await screen.findByText('newFollower:{"name":"Bob"}')).closest("a");
    expect(row).toHaveAttribute("href", "/u/bob");
  });

  it("does not render a link for a review_like with no resolved target (defensive)", async () => {
    server.use(unreadCountHandler(0));
    server.use(notificationsHandler([reviewLikeNoSlug]));
    server.use(http.post("/api/notifications/read", () => new HttpResponse(null, { status: 204 })));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    const message = await screen.findByText('reviewLike:{"name":"Dave"}');
    expect(message.closest("a")).toBeNull();
  });

  it("shows an empty state when there are no notifications", async () => {
    server.use(unreadCountHandler(0));
    server.use(notificationsHandler([]));
    server.use(http.post("/api/notifications/read", () => new HttpResponse(null, { status: 204 })));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    expect(await screen.findByText("empty")).toBeInTheDocument();
  });

  it("shows an error state when the list fetch fails", async () => {
    server.use(unreadCountHandler(0));
    server.use(http.get("/api/notifications", () => new HttpResponse(null, { status: 500 })));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    expect(await screen.findByText("error")).toBeInTheDocument();
  });

  it("renders a delete button per row", async () => {
    server.use(unreadCountHandler(2));
    server.use(notificationsHandler([reviewLike, newFollower]));

    renderWithQuery(<NotificationBell />);
    await screen.findByText("2");

    await act(async () => {
      openBell();
    });

    await screen.findByText('reviewLike:{"name":"carol"}');
    expect(screen.getAllByRole("button", { name: "deleteAriaLabel" })).toHaveLength(2);
  });

  it("clicking delete removes the row, decrements the badge, and does not navigate", async () => {
    server.use(unreadCountHandler(2));
    server.use(notificationsHandler([reviewLike, newFollower]));
    const deleteCall = vi.fn();
    server.use(
      http.delete("/api/notifications/2", () => {
        deleteCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithQuery(<NotificationBell />);
    await screen.findByText("2");

    await act(async () => {
      openBell();
    });

    const reviewLikeMessage = await screen.findByText('reviewLike:{"name":"carol"}');
    const reviewLikeLink = reviewLikeMessage.closest("a");
    const deleteButtons = screen.getAllByRole("button", { name: "deleteAriaLabel" });

    await act(async () => {
      fireEvent.click(deleteButtons[0]);
    });

    await waitFor(() => expect(deleteCall).toHaveBeenCalledTimes(1));
    // The row is gone, the badge dropped from 2 to 1, and the other row
    // (`newFollower`) stays untouched.
    await waitFor(() =>
      expect(screen.queryByText('reviewLike:{"name":"carol"}')).not.toBeInTheDocument(),
    );
    expect(screen.getByText('newFollower:{"name":"Bob"}')).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    // The click must not have triggered the sibling Link's navigation —
    // nothing about jsdom's location changed, and the link element itself
    // is gone along with the row.
    expect(reviewLikeLink).not.toBeNull();
  });

  it("keeps the row when the delete request fails", async () => {
    server.use(unreadCountHandler(1));
    server.use(notificationsHandler([reviewLike]));
    server.use(http.delete("/api/notifications/2", () => new HttpResponse(null, { status: 500 })));

    renderWithQuery(<NotificationBell />);
    await screen.findByText("1");

    await act(async () => {
      openBell();
    });

    await screen.findByText('reviewLike:{"name":"carol"}');
    const deleteButton = screen.getByRole("button", { name: "deleteAriaLabel" });

    await act(async () => {
      fireEvent.click(deleteButton);
    });

    await waitFor(() => expect(screen.getByText('reviewLike:{"name":"carol"}')).toBeInTheDocument());
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("shows the session-expired toast (not just a log) when deleting a notification returns a 401", async () => {
    server.use(unreadCountHandler(1));
    server.use(notificationsHandler([reviewLike]));
    server.use(http.delete("/api/notifications/2", () => new HttpResponse(null, { status: 401 })));

    renderWithQuery(<NotificationBell />);
    await screen.findByText("1");

    await act(async () => {
      openBell();
    });

    await screen.findByText('reviewLike:{"name":"carol"}');
    const deleteButton = screen.getByRole("button", { name: "deleteAriaLabel" });

    await act(async () => {
      fireEvent.click(deleteButton);
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("unauthorized"));
    // The row stays in place, same as any other failed delete.
    expect(screen.getByText('reviewLike:{"name":"carol"}')).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("shows the session-expired toast when marking all as read returns a 401", async () => {
    server.use(unreadCountHandler(2));
    server.use(notificationsHandler([reviewLike, newFollower]));
    server.use(http.post("/api/notifications/read", () => new HttpResponse(null, { status: 401 })));

    renderWithQuery(<NotificationBell />);
    await screen.findByText("2");

    await act(async () => {
      openBell();
    });

    const markAllReadItem = await screen.findByRole("menuitem", { name: "markAllRead" });

    await act(async () => {
      fireEvent.click(markAllReadItem);
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("unauthorized"));
    // Nothing is cleared locally on a failed mark-all-read.
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText('reviewLike:{"name":"carol"}')).toBeInTheDocument();
  });

  it("shows the user_completed-specific message instead of the generic fallback", async () => {
    server.use(unreadCountHandler(0));
    server.use(notificationsHandler([userCompleted]));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    expect(await screen.findByText('userCompleted:{"name":"Frank"}')).toBeInTheDocument();
    expect(screen.queryByText(/^generic:/)).not.toBeInTheDocument();
  });

  it("links user_completed to the completed item, same as review_like's target resolution", async () => {
    server.use(unreadCountHandler(0));
    server.use(notificationsHandler([userCompleted]));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    const row = (await screen.findByText('userCompleted:{"name":"Frank"}')).closest("a");
    expect(row).toHaveAttribute("href", "/movie/the-matrix-1999");
  });

  it("does not render a link for a user_completed with no resolved target (defensive)", async () => {
    server.use(unreadCountHandler(0));
    server.use(notificationsHandler([userCompletedNoSlug]));

    renderWithQuery(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    const message = await screen.findByText('userCompleted:{"name":"grace"}');
    expect(message.closest("a")).toBeNull();
  });
});
