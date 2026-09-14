import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Namespace-prefixed echo, same approach as `trending/page.test.tsx`/
// `recommendations/page.test.tsx`: the page body reads from two namespaces
// (`Profile` for its own copy, `Browse` for the library preview's type
// badge) and the prefix is what tells them apart. `t(key, vars)` echoes as
// `ns:key:{"var":"value"}`, the interpolated-key convention of
// `admin/users/[username]/page.test.tsx`, since several keys take vars
// (`followingCount`, `reviews.dateLabel`, ...). `generateMetadata` calls
// `getTranslations({ locale, namespace })` with an options object rather
// than a bare string, hence the two shapes handled below.
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string | { namespace?: string }) => {
    const name = typeof namespace === "string" ? namespace : (namespace?.namespace ?? "");
    return (key: string, vars?: Record<string, unknown>) =>
      vars ? `${name}:${key}:${JSON.stringify(vars)}` : `${name}:${key}`;
  },
  setRequestLocale: vi.fn(),
}));

// Kept as a spy (rather than an inline throwing mock) so the render suite
// below can assert that a 404 username — and ONLY a 404 username — reaches
// `notFound()`; it still throws, because that is what the real one does to
// halt rendering.
const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
vi.mock("next/navigation", () => ({
  notFound: () => notFound(),
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({
    href,
    children,
    ...props
  }: {
    href: string | object;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : JSON.stringify(href)} {...props}>
      {children}
    </a>
  ),
}));

// `@/lib/library`/`@/lib/search`/`@/lib/user-content`/`@/lib/api-fetch` all
// transitively import `server-only` (via `@/lib/auth/session`) — mocked
// wholesale so this file never has to satisfy that import outside a real
// Next server runtime, same rationale as
// `admin/users/[username]/page.test.tsx`.
const getUserProfile = vi.fn();
const getUserLibrary = vi.fn();
vi.mock("@/lib/library", () => ({
  getUserProfile: (username: string) => getUserProfile(username),
  getUserLibrary: (username: string, query: unknown) => getUserLibrary(username, query),
}));

// Only the network side of `@/lib/search` is unavailable here; its
// `toCatalogType` is a re-export of the framework-agnostic (and therefore
// `server-only`-free) `@/lib/catalog-types`, so the REAL mapping is handed
// back — same as `search/page.test.tsx`/`recommendations/page.test.tsx`.
// This used to be `(value: string) => value`, an identity stand-in that
// existed purely to resolve the module for the metadata tests and that no
// test ever executed; the library-preview cases below are what make the
// real function necessary (issue #37).
vi.mock("@/lib/search", async () => {
  const { toCatalogType } = await import("@/lib/catalog-types");
  return { toCatalogType };
});

const getUserReviews = vi.fn();
vi.mock("@/lib/user-content", () => ({
  getUserReviews: (username: string, query: unknown) => getUserReviews(username, query),
}));

const getCurrentUser = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  getCurrentUser: () => getCurrentUser(),
}));

// `FollowWidget`/`LibraryStatusCounts` are Client Components (session
// fetching, react-query) and `ProfileReviewsPagination` is an async Server
// Component that real ReactDOM can't render as a child — all three are
// stubbed to expose their props, the same way `search/page.test.tsx` stubs
// `SearchControls`/`SearchPagination`. `CatalogCard`/`UserReviewCard` have
// their own dedicated suites; stubbing them keeps the assertions here on
// what THIS page decides (which link, which label, which review).
vi.mock("@/components/follow-widget", () => ({
  FollowWidget: (props: Record<string, unknown>) => (
    <div data-testid="follow-widget" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/library-status-counts", () => ({
  LibraryStatusCounts: (props: Record<string, unknown>) => (
    <div data-testid="library-status-counts" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/profile-reviews-pagination", () => ({
  ProfileReviewsPagination: (props: Record<string, unknown>) => (
    <div data-testid="reviews-pagination" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/catalog-card", () => ({
  CatalogCard: (props: Record<string, unknown>) => (
    <div data-testid="catalog-card" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/user-review-card", () => ({
  UserReviewCard: ({ review }: { review: { id: number; item: { title: string } } }) => (
    <div data-testid={`review-${review.id}`}>{review.item.title}</div>
  ),
}));

const { default: UserProfilePage, generateMetadata } = await import("./page");

const aliceProfile = {
  username: "alice",
  display_name: "Alice A.",
  bio: "Loves sci-fi.",
  avatar_url: null,
  follower_count: 3,
  following_count: 5,
  library_counts: { want: 1, in_progress: 2, completed: 3, dropped: 0 },
};

function buildProps(username: string, locale = "en") {
  return {
    params: Promise.resolve({ locale, username }),
    searchParams: Promise.resolve({}),
  };
}

describe("generateMetadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns {} when the profile doesn't resolve", async () => {
    getUserProfile.mockResolvedValue({ status: "not-found" });

    const metadata = await generateMetadata(buildProps("ghost"));

    expect(metadata).toEqual({});
  });

  it("sets an autocanonical URL for the profile", async () => {
    getUserProfile.mockResolvedValue({ status: "ok", profile: aliceProfile });

    const metadata = await generateMetadata(buildProps("alice"));

    expect(metadata.alternates).toEqual({ canonical: "/en/u/alice" });
  });

  it("builds the canonical from the actual locale/username params", async () => {
    getUserProfile.mockResolvedValue({ status: "ok", profile: aliceProfile });

    const metadata = await generateMetadata(buildProps("alice", "es"));

    expect(metadata.alternates).toEqual({ canonical: "/es/u/alice" });
  });

  // The three cases above only assert `alternates`, so `title`/`description`/
  // `openGraph.images` — including this function's OWN
  // `display_name ?? username` fallback, a second copy of the one in the page
  // body — had no cover. Both `??` branches of the OG image are here too.
  it("titles and describes the profile, falling back to the branded OG image with no avatar", async () => {
    getUserProfile.mockResolvedValue({ status: "ok", profile: aliceProfile });

    const metadata = await generateMetadata(buildProps("alice"));

    expect(metadata.title).toBe('Metadata.profile:title:{"name":"Alice A."}');
    expect(metadata.description).toBe("Loves sci-fi.");
    expect(metadata.openGraph).toMatchObject({
      title: 'Metadata.profile:title:{"name":"Alice A."}',
      description: "Loves sci-fi.",
      images: ["/opengraph-image"],
    });
  });

  it("names an avatar-less, bio-less profile by its username and uses the avatar when set", async () => {
    getUserProfile.mockResolvedValue({
      status: "ok",
      profile: { ...aliceProfile, display_name: null, bio: null, avatar_url: "https://cdn/a.png" },
    });

    const metadata = await generateMetadata(buildProps("alice"));

    expect(metadata.title).toBe('Metadata.profile:title:{"name":"alice"}');
    expect(metadata.description).toBe('Metadata.profile:descriptionFallback:{"name":"alice"}');
    expect(metadata.openGraph).toMatchObject({ images: ["https://cdn/a.png"] });
  });
});

/**
 * Render suite for the page body (issue #37). Until now this file imported
 * `generateMetadata` alone, so the whole public profile — header, library
 * preview and reviews section — had no safety net at all, and the one
 * surface where it maps a backend `item_type` to a route was invisible to
 * the mutation check that measured which suites catch a broken
 * `toCatalogType`.
 */
function libraryEntry(itemType: string, slug: string, title: string) {
  return {
    item: {
      item_type: itemType,
      slug,
      title,
      poster_url: null,
      release_date: null,
      rating_external: null,
      rating_internal: null,
    },
    status: "completed",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function review(id: number, title: string) {
  return {
    id,
    item: { item_type: "MOVIE", title, slug: `${title.toLowerCase()}-2021` },
    score: 4,
    review_text: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function renderProps(username: string, query: Record<string, string> = {}, locale = "en") {
  return {
    params: Promise.resolve({ locale, username }),
    searchParams: Promise.resolve(query),
  };
}

function cards() {
  return screen
    .getAllByTestId("catalog-card")
    .map((node) => JSON.parse(node.dataset.props ?? "{}") as Record<string, unknown>);
}

function stubProps(testId: string) {
  return JSON.parse(screen.getByTestId(testId).dataset.props ?? "{}") as Record<string, unknown>;
}

function defaultMocks() {
  getUserProfile.mockResolvedValue({ status: "ok", profile: aliceProfile });
  getUserLibrary.mockResolvedValue({ ok: true, items: [], total: 0, page: 1, limit: 6 });
  getUserReviews.mockResolvedValue({ ok: true, items: [], total: 0, page: 1, limit: 10 });
  getCurrentUser.mockResolvedValue(null);
}

beforeEach(() => {
  vi.clearAllMocks();
  defaultMocks();
});

describe("UserProfilePage — header", () => {
  it("renders the profile's name, handle, bio and follow widget", async () => {
    render(await UserProfilePage(renderProps("alice")));

    expect(screen.getByRole("heading", { name: "Alice A.", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("Loves sci-fi.")).toBeInTheDocument();
    expect(screen.getByText('Profile:followingCount:{"count":5}')).toBeInTheDocument();
    expect(stubProps("follow-widget")).toMatchObject({
      username: "alice",
      initialFollowerCount: 3,
      isOwnProfile: false,
    });
  });

  it("falls back to the username when there is no display name", async () => {
    getUserProfile.mockResolvedValue({
      status: "ok",
      profile: { ...aliceProfile, display_name: null, bio: null },
    });

    render(await UserProfilePage(renderProps("alice")));

    expect(screen.getByRole("heading", { name: "alice", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("AL")).toBeInTheDocument();
  });

  it("offers the edit link — and marks the widget as own — on your own profile", async () => {
    getCurrentUser.mockResolvedValue({ username: "alice" });

    render(await UserProfilePage(renderProps("alice")));

    expect(screen.getByRole("link", { name: "Profile:editProfileLink" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(stubProps("follow-widget")).toMatchObject({ isOwnProfile: true });
  });

  it("hides the edit link when the viewer is someone else", async () => {
    getCurrentUser.mockResolvedValue({ username: "bob" });

    render(await UserProfilePage(renderProps("alice")));

    expect(screen.queryByText("Profile:editProfileLink")).not.toBeInTheDocument();
    expect(stubProps("follow-widget")).toMatchObject({ isOwnProfile: false });
  });
});

describe("UserProfilePage — profile that doesn't load", () => {
  it("calls notFound() for a username the backend 404s", async () => {
    getUserProfile.mockResolvedValue({ status: "not-found" });

    await expect(UserProfilePage(renderProps("ghost"))).rejects.toThrow("NEXT_NOT_FOUND");

    expect(notFound).toHaveBeenCalled();
  });

  it("shows an inline error — not a 404 — when the profile fetch fails", async () => {
    getUserProfile.mockResolvedValue({ status: "error" });

    render(await UserProfilePage(renderProps("alice")));

    expect(notFound).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Profile:error");
    expect(screen.queryByTestId("follow-widget")).not.toBeInTheDocument();
  });
});

describe("UserProfilePage — library preview", () => {
  it("links every preview entry to its own type's route, labelled from the Browse namespace", async () => {
    getUserLibrary.mockResolvedValue({
      ok: true,
      items: [
        libraryEntry("MOVIE", "dune-2021", "Dune"),
        libraryEntry("SERIES", "chernobyl", "Chernobyl"),
        libraryEntry("BOOK", "hyperion", "Hyperion"),
        libraryEntry("GAME", "hades", "Hades"),
      ],
      total: 4,
      page: 1,
      limit: 6,
    });

    render(await UserProfilePage(renderProps("alice")));

    expect(cards().map((card) => card.href)).toEqual([
      "/movie/dune-2021",
      "/series/chernobyl",
      "/book/hyperion",
      "/game/hades",
    ]);
    expect(cards().map((card) => card.typeLabel)).toEqual([
      "Browse:heading.movie",
      "Browse:heading.series",
      "Browse:heading.book",
      "Browse:heading.game",
    ]);
    expect(getUserLibrary).toHaveBeenCalledWith("alice", { limit: 6 });
  });

  it("renders an entry whose item_type has no route without a link", async () => {
    // Issue #37, the case this suite exists for: the page's rule is
    // `href={itemType ? ... : undefined}`, so an unmapped type degrades to
    // an unlinked card showing the raw backend value — never a confident
    // `/podcast/{slug}` link, which wouldn't merely 404 (see
    // `toCatalogType`'s doc comment).
    getUserLibrary.mockResolvedValue({
      ok: true,
      items: [
        libraryEntry("PODCAST", "the-rest-is-history", "The Rest Is History"),
        libraryEntry("MOVIE", "dune-2021", "Dune"),
      ],
      total: 2,
      page: 1,
      limit: 6,
    });

    render(await UserProfilePage(renderProps("alice")));

    expect(cards()).toHaveLength(2);
    expect(cards()[0]).toMatchObject({ title: "The Rest Is History", typeLabel: "PODCAST" });
    // Both absent from the serialized props: `undefined` is what the page
    // passes for an unmapped type, and `JSON.stringify` drops such keys.
    expect(cards()[0].href).toBeUndefined();
    expect(cards()[0].itemType).toBeUndefined();
    expect(cards()[1].href).toBe("/movie/dune-2021");
  });

  it("keeps the counts summary and drops the preview grid when the library fetch fails", async () => {
    getUserLibrary.mockResolvedValue({ ok: false });

    render(await UserProfilePage(renderProps("alice")));

    expect(screen.queryAllByTestId("catalog-card")).toHaveLength(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(stubProps("library-status-counts")).toMatchObject({
      username: "alice",
      counts: aliceProfile.library_counts,
    });
  });
});

describe("UserProfilePage — reviews", () => {
  it("renders one card per review and sizes the pagination from total/limit", async () => {
    getUserReviews.mockResolvedValue({
      ok: true,
      items: [review(1, "Dune"), review(2, "Arrival")],
      total: 25,
      page: 1,
      limit: 10,
    });

    render(await UserProfilePage(renderProps("alice")));

    expect(screen.getByTestId("review-1")).toHaveTextContent("Dune");
    expect(screen.getByTestId("review-2")).toHaveTextContent("Arrival");
    expect(stubProps("reviews-pagination")).toMatchObject({
      username: "alice",
      page: 1,
      totalPages: 3,
    });
  });

  it("reads ?page= for the reviews query, falling back to page 1 for junk", async () => {
    await UserProfilePage(renderProps("alice", { page: "4" }));
    expect(getUserReviews).toHaveBeenCalledWith("alice", { page: 4, limit: 10 });

    await UserProfilePage(renderProps("alice", { page: "-2" }));
    expect(getUserReviews).toHaveBeenLastCalledWith("alice", { page: 1, limit: 10 });
  });

  it("shows the empty state when the user hasn't reviewed anything", async () => {
    render(await UserProfilePage(renderProps("alice")));

    expect(screen.getByText("Profile:reviews.empty")).toBeInTheDocument();
    expect(screen.queryByTestId("reviews-pagination")).not.toBeInTheDocument();
  });

  it("degrades to a reviews-only error, keeping the header and library", async () => {
    getUserReviews.mockResolvedValue({ ok: false });

    render(await UserProfilePage(renderProps("alice")));

    expect(screen.getByRole("alert")).toHaveTextContent("Profile:reviews.error");
    expect(screen.getByTestId("follow-widget")).toBeInTheDocument();
    expect(screen.getByTestId("library-status-counts")).toBeInTheDocument();
  });
});
