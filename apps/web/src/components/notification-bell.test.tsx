import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

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

const alreadyRead = {
  id: 4,
  type: "new_follower",
  actor: { username: "erin", display_name: "Erin", avatar_url: null },
  target: { target_type: null, target_id: null, item_type: null, slug: null },
  is_read: true,
  created_at: "2026-05-25T18:04:11Z",
};

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("NotificationBell", () => {
  it("shows no badge when the unread count is 0", async () => {
    server.use(unreadCountHandler(0));

    render(<NotificationBell />);

    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-label", "bellLabel"));
    expect(screen.queryByText("3")).not.toBeInTheDocument();
  });

  it("shows the unread count as a badge once loaded", async () => {
    server.use(unreadCountHandler(3));

    render(<NotificationBell />);

    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-label",
      'bellLabelUnread:{"count":3}',
    );
  });

  it("caps the visible badge at 99+", async () => {
    server.use(unreadCountHandler(150));

    render(<NotificationBell />);

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

    render(<NotificationBell />);
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

    render(<NotificationBell />);
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

    render(<NotificationBell />);

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

    render(<NotificationBell />);
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

    render(<NotificationBell />);

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

    render(<NotificationBell />);

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

    render(<NotificationBell />);

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

    render(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    expect(await screen.findByText("empty")).toBeInTheDocument();
  });

  it("shows an error state when the list fetch fails", async () => {
    server.use(unreadCountHandler(0));
    server.use(http.get("/api/notifications", () => new HttpResponse(null, { status: 500 })));

    render(<NotificationBell />);

    await act(async () => {
      openBell();
    });

    expect(await screen.findByText("error")).toBeInTheDocument();
  });

  it("renders a delete button per row", async () => {
    server.use(unreadCountHandler(2));
    server.use(notificationsHandler([reviewLike, newFollower]));

    render(<NotificationBell />);
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

    render(<NotificationBell />);
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

    render(<NotificationBell />);
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
  });
});
