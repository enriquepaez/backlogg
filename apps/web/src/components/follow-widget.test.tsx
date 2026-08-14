import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `item-reviews.test.tsx` for mocking `@/i18n/navigation`
// (the followers-count link + the anonymous login link) and `next-intl`
// (assertions match on message keys, including dotted nested keys like
// "follow.follow", instead of needing a real `NextIntlClientProvider`).
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
}));

const { FollowWidget } = await import("./follow-widget");

function statusHandler(body: { authenticated: boolean; following: boolean }) {
  return http.get("/api/users/alice/follow", () => HttpResponse.json(body));
}

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("FollowWidget", () => {
  it("renders the follower count and no button while isOwnProfile", () => {
    render(<FollowWidget username="alice" initialFollowerCount={3} isOwnProfile />);

    expect(screen.getByText('followersCount:{"count":3}')).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "follow.follow" })).not.toBeInTheDocument();
  });

  it("renders a login link for an anonymous viewer", async () => {
    server.use(statusHandler({ authenticated: false, following: false }));

    render(<FollowWidget username="alice" initialFollowerCount={3} isOwnProfile={false} />);

    const link = await screen.findByRole("link", { name: "follow.follow" });
    expect(link).toHaveAttribute("href", "/login");
  });

  it("renders an unpressed follow button when the viewer doesn't already follow", async () => {
    server.use(statusHandler({ authenticated: true, following: false }));

    render(<FollowWidget username="alice" initialFollowerCount={3} isOwnProfile={false} />);

    const button = await screen.findByRole("button", { name: "follow.follow" });
    expect(button).toHaveAttribute("aria-pressed", "false");
  });

  it("renders a pressed unfollow button when the viewer already follows", async () => {
    server.use(statusHandler({ authenticated: true, following: true }));

    render(<FollowWidget username="alice" initialFollowerCount={3} isOwnProfile={false} />);

    const button = await screen.findByRole("button", { name: "follow.unfollow" });
    expect(button).toHaveAttribute("aria-pressed", "true");
  });

  it("optimistically follows, bumping the follower count, then confirms on a 204", async () => {
    server.use(statusHandler({ authenticated: true, following: false }));
    const followCall = vi.fn();
    server.use(
      http.post("/api/users/alice/follow", () => {
        followCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<FollowWidget username="alice" initialFollowerCount={3} isOwnProfile={false} />);
    const button = await screen.findByRole("button", { name: "follow.follow" });

    await act(async () => {
      fireEvent.click(button);
    });

    expect(followCall).toHaveBeenCalledTimes(1);
    expect(screen.getByText('followersCount:{"count":4}')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "follow.unfollow" })).toHaveAttribute("aria-pressed", "true");
  });

  it("unfollows via DELETE, dropping the follower count", async () => {
    server.use(statusHandler({ authenticated: true, following: true }));
    const unfollowCall = vi.fn();
    server.use(
      http.delete("/api/users/alice/follow", () => {
        unfollowCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<FollowWidget username="alice" initialFollowerCount={3} isOwnProfile={false} />);
    const button = await screen.findByRole("button", { name: "follow.unfollow" });

    await act(async () => {
      fireEvent.click(button);
    });

    expect(unfollowCall).toHaveBeenCalledTimes(1);
    expect(screen.getByText('followersCount:{"count":2}')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "follow.follow" })).toHaveAttribute("aria-pressed", "false");
  });

  it("reverts the optimistic follow (button and count) when the backend request fails", async () => {
    server.use(statusHandler({ authenticated: true, following: false }));
    server.use(http.post("/api/users/alice/follow", () => new HttpResponse(null, { status: 500 })));

    render(<FollowWidget username="alice" initialFollowerCount={3} isOwnProfile={false} />);
    const button = await screen.findByRole("button", { name: "follow.follow" });

    await act(async () => {
      fireEvent.click(button);
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "follow.follow" })).toHaveAttribute("aria-pressed", "false"),
    );
    expect(screen.getByText('followersCount:{"count":3}')).toBeInTheDocument();
  });

  it("ignores a second click while the first toggle is still in flight", async () => {
    server.use(statusHandler({ authenticated: true, following: false }));
    const followCall = vi.fn();
    let resolveRequest: (() => void) | undefined;
    server.use(
      http.post("/api/users/alice/follow", async () => {
        followCall();
        await new Promise<void>((resolve) => {
          resolveRequest = resolve;
        });
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<FollowWidget username="alice" initialFollowerCount={3} isOwnProfile={false} />);
    const button = await screen.findByRole("button", { name: "follow.follow" });

    act(() => {
      fireEvent.click(button);
    });

    await waitFor(() => expect(button).toBeDisabled());
    fireEvent.click(button);
    fireEvent.click(button);

    await act(async () => {
      resolveRequest?.();
    });

    expect(followCall).toHaveBeenCalledTimes(1);
    expect(screen.getByText('followersCount:{"count":4}')).toBeInTheDocument();
  });
});
