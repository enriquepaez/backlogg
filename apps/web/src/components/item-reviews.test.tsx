import { act } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `rating-widget.test.tsx` for mocking `@/i18n/navigation`
// (the author link + the anonymous like link) and `next-intl` (assertions
// match on message keys, including dotted nested keys like
// "pagination.previous", instead of needing a real
// `NextIntlClientProvider`).
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

const { ItemReviews } = await import("./item-reviews");

function renderReviews() {
  return render(<ItemReviews type="movie" slug="dune-2021" />);
}

const bob = {
  id: 1,
  user: { username: "bob", display_name: "Bob", avatar_url: null },
  score: 4,
  review_text: "Loved it",
  like_count: 2,
  liked_by_viewer: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const alice = {
  id: 2,
  user: { username: "alice", display_name: null, avatar_url: "https://example.com/alice.png" },
  score: null,
  review_text: null,
  like_count: 0,
  liked_by_viewer: false,
  created_at: "2026-01-02T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

function reviewsHandler(items: unknown[], overrides: Record<string, unknown> = {}) {
  return http.get("/api/movie/dune-2021/ratings", () =>
    HttpResponse.json({ authenticated: true, items, total: items.length, page: 1, limit: 10, ...overrides }),
  );
}

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("ItemReviews", () => {
  it("shows an empty state when there are no reviews", async () => {
    server.use(reviewsHandler([]));

    renderReviews();

    expect(await screen.findByText("empty")).toBeInTheDocument();
  });

  it("shows a load error when the fetch fails", async () => {
    server.use(http.get("/api/movie/dune-2021/ratings", () => new HttpResponse(null, { status: 500 })));

    renderReviews();

    expect(await screen.findByText("loadError")).toBeInTheDocument();
  });

  it("renders each review's author, score, text and like count", async () => {
    server.use(reviewsHandler([bob]));

    renderReviews();

    expect(await screen.findByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("Loved it")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Bob/ })).toHaveAttribute("href", "/u/bob");
    expect(screen.getByText('likeCount:{"count":2}')).toBeInTheDocument();
  });

  it("renders a half-filled star for a review with a .5 score", async () => {
    server.use(reviewsHandler([{ ...bob, score: 3.5 }]));

    const { container } = renderReviews();

    await screen.findByText("Bob");
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);
  });

  // FE-47: `ReviewStars` (a `StarRating` wrapper) is the only renderer of a
  // review's stars — confirms this call site inherits the `role="img"` +
  // `aria-label` fix without any changes of its own.
  it("exposes each review's score to assistive tech via role=img + aria-label", async () => {
    server.use(reviewsHandler([bob]));

    const { container } = renderReviews();

    await screen.findByText("Bob");
    expect(container.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(
      'ariaLabel:{"value":4}',
    );
  });

  it("falls back to username and initials when display_name/avatar are missing", async () => {
    server.use(reviewsHandler([alice]));

    renderReviews();

    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /alice/ })).toHaveAttribute("href", "/u/alice");
  });

  it("shows an avatar image instead of initials when avatar_url is set", async () => {
    server.use(reviewsHandler([alice]));

    const { container } = renderReviews();

    await screen.findByText("alice");
    expect(container.querySelector("img")).toHaveAttribute("src", "https://example.com/alice.png");
  });

  it("does not render review text when review_text is null", async () => {
    server.use(reviewsHandler([alice]));

    renderReviews();

    await screen.findByText("alice");
    expect(screen.queryByText("Loved it")).not.toBeInTheDocument();
  });

  it("renders a like button (not a login link) for an authenticated viewer", async () => {
    server.use(reviewsHandler([bob], { authenticated: true }));

    renderReviews();

    const likeButton = await screen.findByRole("button", { name: "likeAriaLabel" });
    expect(likeButton).toHaveAttribute("aria-pressed", "false");
  });

  it("starts a review already liked by the viewer with the heart in a liked state", async () => {
    server.use(
      reviewsHandler([{ ...bob, liked_by_viewer: true }], { authenticated: true }),
    );

    renderReviews();

    const likeButton = await screen.findByRole("button", { name: "unlikeAriaLabel" });
    expect(likeButton).toHaveAttribute("aria-pressed", "true");
  });

  it("renders a login link (not a button) for an anonymous viewer", async () => {
    server.use(reviewsHandler([bob], { authenticated: false }));

    renderReviews();

    await screen.findByText("Bob");
    expect(screen.queryByRole("button", { name: "likeAriaLabel" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "likeAriaLabel" })).toHaveAttribute("href", "/login");
  });

  it("optimistically likes a review, then confirms on a 204 from the backend", async () => {
    server.use(reviewsHandler([bob], { authenticated: true }));
    const likeCall = vi.fn();
    server.use(
      http.post("/api/reviews/1/like", () => {
        likeCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderReviews();
    const likeButton = await screen.findByRole("button", { name: "likeAriaLabel" });

    await act(async () => {
      fireEvent.click(likeButton);
    });

    expect(likeCall).toHaveBeenCalledTimes(1);
    expect(screen.getByText('likeCount:{"count":3}')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "unlikeAriaLabel" })).toHaveAttribute("aria-pressed", "true");
  });

  it("reverts the optimistic like when the backend request fails", async () => {
    server.use(reviewsHandler([bob], { authenticated: true }));
    server.use(http.post("/api/reviews/1/like", () => new HttpResponse(null, { status: 500 })));

    renderReviews();
    const likeButton = await screen.findByRole("button", { name: "likeAriaLabel" });

    await act(async () => {
      fireEvent.click(likeButton);
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "likeAriaLabel" })).toHaveAttribute("aria-pressed", "false"),
    );
    expect(screen.getByText('likeCount:{"count":2}')).toBeInTheDocument();
  });

  it("unlikes a previously (optimistically) liked review via DELETE", async () => {
    server.use(reviewsHandler([bob], { authenticated: true }));
    server.use(http.post("/api/reviews/1/like", () => new HttpResponse(null, { status: 204 })));
    const unlikeCall = vi.fn();
    server.use(
      http.delete("/api/reviews/1/like", () => {
        unlikeCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderReviews();
    const likeButton = await screen.findByRole("button", { name: "likeAriaLabel" });

    await act(async () => {
      fireEvent.click(likeButton);
    });
    await screen.findByRole("button", { name: "unlikeAriaLabel" });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "unlikeAriaLabel" }));
    });

    expect(unlikeCall).toHaveBeenCalledTimes(1);
    expect(screen.getByText('likeCount:{"count":2}')).toBeInTheDocument();
  });

  it("ignores a second click on the same review while the first like request is still in flight", async () => {
    server.use(reviewsHandler([bob], { authenticated: true }));
    const likeCall = vi.fn();
    let resolveRequest: (() => void) | undefined;
    server.use(
      http.post("/api/reviews/1/like", async () => {
        likeCall();
        await new Promise<void>((resolve) => {
          resolveRequest = resolve;
        });
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderReviews();
    const likeButton = await screen.findByRole("button", { name: "likeAriaLabel" });

    act(() => {
      fireEvent.click(likeButton);
    });

    // The button is disabled while the request is in flight — the guard in
    // `toggleLike` is a belt-and-braces no-op even if a click somehow slips
    // through (e.g. a keyboard-triggered click event bypassing `disabled`).
    await waitFor(() => expect(likeButton).toBeDisabled());
    fireEvent.click(likeButton);
    fireEvent.click(likeButton);

    await act(async () => {
      resolveRequest?.();
    });

    expect(likeCall).toHaveBeenCalledTimes(1);
    expect(screen.getByText('likeCount:{"count":3}')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "unlikeAriaLabel" })).not.toBeDisabled();
  });

  it("does not render pagination controls when there is only one page", async () => {
    server.use(reviewsHandler([bob], { total: 1, limit: 10 }));

    renderReviews();

    await screen.findByText("Bob");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("renders pagination and requests the next page on click", async () => {
    server.use(
      http.get("/api/movie/dune-2021/ratings", ({ request }) => {
        const url = new URL(request.url);
        const page = url.searchParams.get("page");
        return HttpResponse.json({
          authenticated: true,
          items: page === "2" ? [alice] : [bob],
          total: 15,
          page: page === "2" ? 2 : 1,
          limit: 10,
        });
      }),
    );

    renderReviews();
    await screen.findByText("Bob");

    const nav = within(screen.getByRole("navigation", { name: "pagination.nav" }));
    expect(nav.getByRole("button", { name: "pagination.previous" })).toBeDisabled();
    expect(screen.getByText('pagination.pageStatus:{"page":1,"totalPages":2}')).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(nav.getByRole("button", { name: "pagination.next" }));
    });

    await screen.findByText("alice");
    expect(screen.queryByText("Bob")).not.toBeInTheDocument();
  });
});
