import { act } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `verify-email-status.test.tsx` for mocking
// `@/i18n/navigation` (the anonymous state's "log in" link) and `next-intl`
// (assertions match on message keys instead of needing a real
// `NextIntlClientProvider`). `sonner`'s `toast` is mocked the same way
// `account-profile-form.test.tsx`/`delete-account-dialog.test.tsx` mock it.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// `(key, vars?)` mirrors `next-intl`'s real interpolation shape closely
// enough for assertions on `aggregateLabel`/`starAriaLabel` (the only two
// call sites in `rating-widget.tsx` that pass `vars`) without pulling in a
// real `NextIntlClientProvider`. Every other call site here has no `vars`
// and keeps resolving to the bare key, as before.
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

const { RatingWidget } = await import("./rating-widget");

const savedRating = {
  id: 42,
  user: { username: "alice", display_name: "Alice", avatar_url: null },
  score: 4,
  review_text: "Loved it",
  like_count: 0,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderWidget() {
  return render(
    <RatingWidget type="movie" slug="dune-2021" initialRatingInternal={4.2} initialRatingCountInternal={87} />,
  );
}

function scoreGroup() {
  return within(screen.getByRole("group", { name: "scoreLabel" }));
}

beforeEach(() => {
  toastSuccess.mockClear();
  toastError.mockClear();
});

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("RatingWidget", () => {
  it("prompts anonymous viewers to log in and never renders the form", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: false, rating: null }),
      ),
    );

    renderWidget();

    expect(await screen.findByText("anonymousPrompt")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "anonymousLoginLink" })).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("group", { name: "scoreLabel" })).not.toBeInTheDocument();
  });

  it("shows an empty composer when the viewer is authenticated with no rating yet", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );

    renderWidget();

    expect(await screen.findByRole("group", { name: "scoreLabel" })).toBeInTheDocument();
    expect(screen.getByLabelText("reviewLabel")).toHaveValue("");
    // No existing rating yet: no "cancel"/"edit"/"delete" affordance.
    expect(screen.queryByRole("button", { name: "cancel" })).not.toBeInTheDocument();
  });

  it("shows the saved rating summary with edit/delete/report actions", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: savedRating }),
      ),
    );

    renderWidget();

    expect(await screen.findByText("Loved it")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "delete" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "openDialog" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "scoreLabel" })).not.toBeInTheDocument();
  });

  it("shows the rater's display name and initials fallback when there is no avatar", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: savedRating }),
      ),
    );

    const { container } = renderWidget();

    expect(await screen.findByText("Alice")).toBeInTheDocument();
    // savedRating.user.avatar_url is null: falls back to initials of
    // display_name ("Alice" -> "AL"), not the img element.
    expect(screen.getByText("AL")).toBeInTheDocument();
    expect(container.querySelector("img")).not.toBeInTheDocument();
  });

  it("shows the rater's avatar image (instead of initials) when avatar_url is set", async () => {
    const ratingWithAvatar = {
      ...savedRating,
      user: { username: "alice", display_name: "Alice", avatar_url: "https://example.com/alice.png" },
    };
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: ratingWithAvatar }),
      ),
    );

    const { container } = renderWidget();

    expect(await screen.findByText("Alice")).toBeInTheDocument();
    // alt="" (decorative, name shown as text right next to it) gives the
    // <img> a "presentation" role rather than "img", so it isn't reachable
    // via `getByRole("img")` — query the element directly instead.
    expect(container.querySelector("img")).toHaveAttribute("src", "https://example.com/alice.png");
    expect(screen.queryByText("AL")).not.toBeInTheDocument();
  });

  it("falls back to the rater's username when display_name is missing", async () => {
    const ratingWithoutDisplayName = {
      ...savedRating,
      user: { username: "bobby", display_name: null, avatar_url: null },
    };
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: ratingWithoutDisplayName }),
      ),
    );

    renderWidget();

    expect(await screen.findByText("bobby")).toBeInTheDocument();
    expect(screen.getByText("BO")).toBeInTheDocument();
  });

  it("shows the creation date but no edited date when the rating was never edited", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: savedRating }),
      ),
    );

    renderWidget();

    expect(await screen.findByText('createdOnLabel:{"date":"January 1, 2026"}')).toBeInTheDocument();
    expect(screen.queryByText(/^editedOnLabel:/)).not.toBeInTheDocument();
  });

  it("also shows the edited date when updated_at differs from created_at", async () => {
    const editedRating = { ...savedRating, updated_at: "2026-01-05T00:00:00Z" };
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: editedRating }),
      ),
    );

    renderWidget();

    expect(await screen.findByText('createdOnLabel:{"date":"January 1, 2026"}')).toBeInTheDocument();
    expect(screen.getByText('editedOnLabel:{"date":"January 5, 2026"}')).toBeInTheDocument();
  });

  it("shows a load error when the initial fetch fails", async () => {
    server.use(http.get("/api/movie/dune-2021/rating", () => new HttpResponse(null, { status: 500 })));

    renderWidget();

    expect(await screen.findByText("loadError")).toBeInTheDocument();
  });

  it("blocks submitting with neither a score nor review text", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );
    const putCall = vi.fn();
    server.use(
      http.put("/api/movie/dune-2021/rating", () => {
        putCall();
        return HttpResponse.json(savedRating);
      }),
    );

    renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    expect(await screen.findByText("empty")).toBeInTheDocument();
    expect(putCall).not.toHaveBeenCalled();
  });

  it("saves a new score + review, forwarding the exact PUT body, and switches to the summary", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );
    let forwardedBody: unknown;
    server.use(
      http.put("/api/movie/dune-2021/rating", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(savedRating);
      }),
    );

    renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    const stars = scoreGroup().getAllByRole("button");
    fireEvent.click(stars[3]); // 4th star = score 4
    fireEvent.change(screen.getByLabelText("reviewLabel"), { target: { value: "Loved it" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    await waitFor(() => expect(forwardedBody).toEqual({ score: 4, review_text: "Loved it" }));
    expect(await screen.findByText("Loved it")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "edit" })).toBeInTheDocument();
    expect(toastSuccess).toHaveBeenCalledWith("saveSuccess");
  });

  // Bugfix (post-FE-18 QA): confirmed via a live reproduction against the
  // real backend + `next dev` that this exact case — the very first rating
  // ever submitted for an item, `initialRatingInternal`/
  // `initialRatingCountInternal` both starting from `null`/`0` — already
  // updates `aggregateLabel` correctly on its own; the actual regression was
  // the item detail page's SSR/ISR cache staying stale across a reload (see
  // `src/lib/catalog.test.ts`'s `itemDetailCacheTag` describe block and
  // `route.test.ts`'s `revalidates the item detail cache tag` tests). This
  // scenario wasn't asserted anywhere before (the "saves a new score +
  // review" test above never inspects `aggregateLabel`) — pinning it down
  // here guards against the exact symptom reported in QA recurring.
  it("reflects the new score in the aggregate label right after saving the item's very first rating", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );
    server.use(
      http.put("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ ...savedRating, score: 4, review_text: "good movie" }),
      ),
    );

    render(
      <RatingWidget type="movie" slug="dune-2021" initialRatingInternal={null} initialRatingCountInternal={0} />,
    );
    await screen.findByRole("group", { name: "scoreLabel" });
    expect(screen.getByText(/^aggregateLabel:/)).toHaveTextContent("noRatings");

    const stars = scoreGroup().getAllByRole("button");
    fireEvent.click(stars[3]); // 4th star = score 4
    fireEvent.change(screen.getByLabelText("reviewLabel"), { target: { value: "good movie" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    await screen.findByText("good movie");
    expect(screen.getByText(/^aggregateLabel:/)).toHaveTextContent("4.0 (1)");
  });

  it("toggles a star off (clears the score) when clicked twice", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );

    renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    const stars = scoreGroup().getAllByRole("button");
    fireEvent.click(stars[2]);
    expect(stars[2]).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(stars[2]);
    expect(stars[2]).toHaveAttribute("aria-pressed", "false");
  });

  it("pre-fills the form from the existing rating when editing, and cancel returns to the summary untouched", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: savedRating }),
      ),
    );

    renderWidget();
    await screen.findByText("Loved it");

    fireEvent.click(screen.getByRole("button", { name: "edit" }));

    expect(screen.getByLabelText("reviewLabel")).toHaveValue("Loved it");
    expect(scoreGroup().getAllByRole("button")[3]).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "cancel" }));

    expect(await screen.findByText("Loved it")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "scoreLabel" })).not.toBeInTheDocument();
  });

  it("deletes the rating and returns to an empty composer", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: savedRating }),
      ),
    );
    const deleteCall = vi.fn();
    server.use(
      http.delete("/api/movie/dune-2021/rating", () => {
        deleteCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWidget();
    await screen.findByText("Loved it");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "delete" }));
    });

    expect(deleteCall).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("group", { name: "scoreLabel" })).toBeInTheDocument();
    expect(screen.getByLabelText("reviewLabel")).toHaveValue("");
    expect(toastSuccess).toHaveBeenCalledWith("deleteSuccess");
  });

  it("shows an unauthorized error and stays in the form on a 401 save", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );
    server.use(http.put("/api/movie/dune-2021/rating", () => new HttpResponse(null, { status: 401 })));

    renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    fireEvent.change(screen.getByLabelText("reviewLabel"), { target: { value: "Loved it" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    expect(await screen.findByText("unauthorized")).toBeInTheDocument();
  });
});
