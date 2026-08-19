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

/**
 * The picker button for a given half-point `value` (e.g. `4` or `3.5`) —
 * matches `rating-widget.tsx`'s `t("starAriaLabel", { value })`, which the
 * `next-intl` mock above turns into `starAriaLabel:{"value":<value>}`. Since
 * FE-44 each star position renders two buttons (left half / right full), so
 * indexing `getAllByRole("button")` by position no longer identifies a
 * unique value — querying by the resolved aria-label does.
 */
function starButton(value: number) {
  return scoreGroup().getByRole("button", { name: `starAriaLabel:${JSON.stringify({ value })}` });
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

  it("renders a half-filled star in the summary when the saved score has a .5 fraction", async () => {
    const halfStarRating = { ...savedRating, score: 3.5 };
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: halfStarRating }),
      ),
    );

    const { container } = renderWidget();

    await screen.findByText("Loved it");
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);
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

    fireEvent.click(starButton(4)); // right half of the 4th star = score 4
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

    fireEvent.click(starButton(4)); // right half of the 4th star = score 4
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

    const star3 = starButton(3);
    fireEvent.click(star3);
    expect(star3).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(star3);
    expect(star3).toHaveAttribute("aria-pressed", "false");
  });

  it("selects a half-point score (3.5) from the left half of a star, distinct from the full 3 and 4", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );
    let forwardedBody: unknown;
    server.use(
      http.put("/api/movie/dune-2021/rating", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ ...savedRating, score: 3.5 });
      }),
    );

    renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    // Left half of the 4th star = 3.5, distinct from the 3rd star's full
    // value (3) and the 4th star's own right half (4).
    fireEvent.click(starButton(3.5));
    expect(starButton(3.5)).toHaveAttribute("aria-pressed", "true");
    expect(starButton(3)).toHaveAttribute("aria-pressed", "false");
    expect(starButton(4)).toHaveAttribute("aria-pressed", "false");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    await waitFor(() => expect(forwardedBody).toEqual({ score: 3.5, review_text: null }));
  });

  // Post-launch QA fix (FE-44): a real Chromium reproduction (throwaway
  // Playwright harness against `next dev`, not this jsdom suite — see
  // `rating-widget.tsx`'s `StarPicker` doc comment) confirmed the picker's
  // click hit-testing was already pixel-accurate; what real mouse users
  // actually struggled with was aiming at a boundary with zero visual
  // feedback before committing. These tests assert the fix at the
  // component-state level (does hovering flip the *previewed* fill without
  // touching the actual selection, does it revert on mouse-leave/blur) —
  // this doesn't re-certify real hit-testing (that's the jsdom trap this
  // exact feature already fell into once), only the state machine driving
  // what gets rendered once a hover/focus event *has* fired.
  it("previews the hovered half-point score's star fill without changing the actual selection until clicked", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );

    const { container } = renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0);

    // Hover (not click) the left half of the 3rd star — previews 2.5: stars
    // 1-2 full, star 3 half.
    fireEvent.mouseEnter(starButton(2.5));

    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);
    // No actual selection was made — every button's real pressed state is
    // still false, only the preview fill changed.
    for (const value of [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]) {
      expect(starButton(value)).toHaveAttribute("aria-pressed", "false");
    }

    // Mouse leaving the whole group reverts the preview back to the (still
    // empty) actual score.
    fireEvent.mouseLeave(screen.getByRole("group", { name: "scoreLabel" }));
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0);
  });

  it("reverts the hover preview to the actually selected score (not empty) once the pointer leaves the group", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );

    const { container } = renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    fireEvent.click(starButton(3.5));
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);

    // Hovering a different star previews something else entirely (full 5,
    // no half star at all)...
    fireEvent.mouseEnter(starButton(5));
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0);

    // ...but leaving the group reverts to the real selection (3.5), not to
    // empty.
    fireEvent.mouseLeave(screen.getByRole("group", { name: "scoreLabel" }));
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);
    expect(starButton(3.5)).toHaveAttribute("aria-pressed", "true");
  });

  it("also previews on keyboard focus, and clears when focus leaves the whole group (not just one button)", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );

    const { container } = renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    fireEvent.focus(starButton(2.5));
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(1);

    // Focus moving to another button INSIDE the same group (e.g. Tab to the
    // next star) must not clear the preview early — only reflect the new
    // target.
    fireEvent.blur(starButton(2.5), { relatedTarget: starButton(3) });
    fireEvent.focus(starButton(3));
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0); // 3 is a full value, no half star

    // Focus leaving the group entirely (e.g. Tab to the review textarea)
    // clears the preview back to the actual (still empty) score.
    fireEvent.blur(starButton(3), { relatedTarget: screen.getByLabelText("reviewLabel") });
    expect(container.querySelectorAll('[data-slot="half-star"]')).toHaveLength(0);
  });

  // Bugfix (post-review, FE-44): the first star's left half would naively
  // compute `position - 0.5 = 0.5`, below the backend's minimum score
  // (`ge=1`, `docs/schema.md`). `StarPicker` special-cases `position === 1`
  // to not render that left-half button at all, so 0.5 is never a
  // selectable option, and clicking anywhere on the first star selects 1.
  it("never offers 0.5 as a selectable option on the first star", async () => {
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: null }),
      ),
    );

    renderWidget();
    await screen.findByRole("group", { name: "scoreLabel" });

    expect(scoreGroup().queryByRole("button", { name: `starAriaLabel:${JSON.stringify({ value: 0.5 })}` })).not.toBeInTheDocument();

    fireEvent.click(starButton(1));
    expect(starButton(1)).toHaveAttribute("aria-pressed", "true");
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
    expect(starButton(4)).toHaveAttribute("aria-pressed", "true"); // savedRating.score is 4

    fireEvent.click(screen.getByRole("button", { name: "cancel" }));

    expect(await screen.findByText("Loved it")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "scoreLabel" })).not.toBeInTheDocument();
  });

  it("pre-fills the half-point button (not the adjoining full ones) when editing an existing X.5 rating", async () => {
    const halfStarRating = { ...savedRating, score: 3.5 };
    server.use(
      http.get("/api/movie/dune-2021/rating", () =>
        HttpResponse.json({ authenticated: true, rating: halfStarRating }),
      ),
    );

    renderWidget();
    await screen.findByText("Loved it");

    fireEvent.click(screen.getByRole("button", { name: "edit" }));

    expect(starButton(3.5)).toHaveAttribute("aria-pressed", "true");
    expect(starButton(3)).toHaveAttribute("aria-pressed", "false");
    expect(starButton(4)).toHaveAttribute("aria-pressed", "false");
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
