import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Same mocking approach as `admin/layout.test.tsx`/`admin/page.test.tsx` for
// `next-intl/server`, extended here with the interpolated-key echo
// `admin-users-directory-panel.test.tsx` uses (`t(key, vars)` serializes as
// `key:{"var":"value"}`) since this page passes vars to several keys
// (`joinedLabel`, `followerCount`, `reviews.dateLabel`, ...).
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string, vars?: Record<string, unknown>) =>
    vars ? `${key}:${JSON.stringify(vars)}` : key,
  setRequestLocale: vi.fn(),
}));

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

const getUserProfile = vi.fn();
vi.mock("@/lib/library", () => ({
  getUserProfile: (username: string) => getUserProfile(username),
  LIBRARY_STATUSES: ["want", "in_progress", "completed", "dropped"],
}));

const getUserReviews = vi.fn();
vi.mock("@/lib/user-content", () => ({
  getUserReviews: (username: string, query: unknown) => getUserReviews(username, query),
}));

const getAdminUserDetail = vi.fn();
vi.mock("@/lib/admin-users", () => ({
  getAdminUserDetail: (username: string) => getAdminUserDetail(username),
}));

const getCurrentUser = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  getCurrentUser: () => getCurrentUser(),
}));

// `AdminUserActionsPanel`/`UserReviewCard` are Client/presentational
// components with their own tests — out of scope here, same rationale
// `admin/page.test.tsx` uses for mocking `AdminStatsPanel`.
vi.mock("@/components/admin-user-actions-panel", () => ({
  AdminUserActionsPanel: (props: Record<string, unknown>) => (
    <div data-testid="admin-user-actions-panel" data-props={JSON.stringify(props)} />
  ),
}));
vi.mock("@/components/user-review-card", () => ({
  UserReviewCard: ({ review }: { review: { id: number; item: { title: string } } }) => (
    <div data-testid={`review-${review.id}`}>{review.item.title}</div>
  ),
}));

const { default: AdminUserDetailPage } = await import("./page");

const aliceProfile = {
  username: "alice",
  display_name: "Alice A.",
  bio: "Loves sci-fi.",
  avatar_url: null,
  follower_count: 3,
  following_count: 5,
  library_counts: { want: 1, in_progress: 2, completed: 3, dropped: 0 },
};

const aliceAdmin = {
  username: "alice",
  display_name: "Alice A.",
  avatar_url: null,
  is_admin: false,
  is_superadmin: false,
  is_banned: false,
  created_at: "2026-05-25T02:03:12Z",
};

function buildProps(username: string, query: Record<string, string> = {}) {
  return {
    params: Promise.resolve({ locale: "en", username }),
    searchParams: Promise.resolve(query),
  };
}

function defaultMocks() {
  getUserProfile.mockResolvedValue({ status: "ok", profile: aliceProfile });
  getUserReviews.mockResolvedValue({ items: [], total: 0, page: 1, limit: 10, ok: true });
  getAdminUserDetail.mockResolvedValue({ status: "ok", user: aliceAdmin });
  getCurrentUser.mockResolvedValue(null);
}

describe("AdminUserDetailPage — not found", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    defaultMocks();
  });

  it("calls notFound() when the profile doesn't exist", async () => {
    getUserProfile.mockResolvedValue({ status: "not-found" });

    await expect(AdminUserDetailPage(buildProps("ghost"))).rejects.toThrow();

    expect(notFound).toHaveBeenCalled();
  });

  it("calls notFound() when the admin detail lookup 404s", async () => {
    getAdminUserDetail.mockResolvedValue({ status: "not-found" });

    await expect(AdminUserDetailPage(buildProps("ghost"))).rejects.toThrow();

    expect(notFound).toHaveBeenCalled();
  });
});

describe("AdminUserDetailPage — profile error", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    defaultMocks();
  });

  it("shows a profile error alert when the profile fetch fails", async () => {
    getUserProfile.mockResolvedValue({ status: "error" });

    render(await AdminUserDetailPage(buildProps("alice")));

    expect(screen.getByRole("alert")).toHaveTextContent("profileError");
  });
});

describe("AdminUserDetailPage — profile + library", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    defaultMocks();
  });

  it("renders the profile header, bio, and follower/following counts", async () => {
    render(await AdminUserDetailPage(buildProps("alice")));

    expect(screen.getByRole("heading", { name: "Alice A." })).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("Loves sci-fi.")).toBeInTheDocument();
    expect(screen.getByText('followerCount:{"count":3}')).toBeInTheDocument();
    expect(screen.getByText('followingCount:{"count":5}')).toBeInTheDocument();
  });

  it("renders per-status library counts", async () => {
    render(await AdminUserDetailPage(buildProps("alice")));

    expect(screen.getByText("want: 1")).toBeInTheDocument();
    expect(screen.getByText("completed: 3")).toBeInTheDocument();
  });
});

describe("AdminUserDetailPage — admin section", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    defaultMocks();
  });

  it("forwards the admin detail and caller's superadmin status to the actions panel", async () => {
    getAdminUserDetail.mockResolvedValue({
      status: "ok",
      user: { ...aliceAdmin, is_admin: true },
    });
    getCurrentUser.mockResolvedValue({ username: "root", is_superadmin: true });

    render(await AdminUserDetailPage(buildProps("alice")));

    const panel = screen.getByTestId("admin-user-actions-panel");
    const props = JSON.parse(panel.getAttribute("data-props") ?? "{}");
    expect(props).toMatchObject({
      username: "alice",
      initialIsAdmin: true,
      initialIsBanned: false,
      isTargetSuperadmin: false,
      callerIsSuperadmin: true,
    });
  });

  it("defaults callerIsSuperadmin to false when there is no session", async () => {
    getCurrentUser.mockResolvedValue(null);

    render(await AdminUserDetailPage(buildProps("alice")));

    const panel = screen.getByTestId("admin-user-actions-panel");
    const props = JSON.parse(panel.getAttribute("data-props") ?? "{}");
    expect(props.callerIsSuperadmin).toBe(false);
  });

  it("shows an inline error instead of the actions panel when the admin fetch fails", async () => {
    getAdminUserDetail.mockResolvedValue({ status: "error", reason: "unauthorized" });

    render(await AdminUserDetailPage(buildProps("alice")));

    expect(screen.queryByTestId("admin-user-actions-panel")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("adminErrors.unauthorized");
  });
});

describe("AdminUserDetailPage — reviews", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    defaultMocks();
  });

  it("shows the empty state when there are no reviews", async () => {
    render(await AdminUserDetailPage(buildProps("alice")));

    expect(screen.getByText("reviews.empty")).toBeInTheDocument();
  });

  it("renders one card per review", async () => {
    getUserReviews.mockResolvedValue({
      ok: true,
      items: [
        { id: 1, item: { item_type: "MOVIE", title: "Dune", slug: "dune-2021" }, score: 4, review_text: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
        { id: 2, item: { item_type: "MOVIE", title: "Arrival", slug: "arrival-2016" }, score: 5, review_text: null, created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" },
      ],
      total: 2,
      page: 1,
      limit: 10,
    });

    render(await AdminUserDetailPage(buildProps("alice")));

    expect(screen.getByTestId("review-1")).toHaveTextContent("Dune");
    expect(screen.getByTestId("review-2")).toHaveTextContent("Arrival");
  });

  it("shows a reviews error alert when the reviews fetch fails", async () => {
    getUserReviews.mockResolvedValue({ ok: false });

    render(await AdminUserDetailPage(buildProps("alice")));

    expect(screen.getByText("reviews.error")).toBeInTheDocument();
  });

  it("renders pagination once there is more than one page", async () => {
    getUserReviews.mockResolvedValue({
      ok: true,
      items: [
        { id: 1, item: { item_type: "MOVIE", title: "Dune", slug: "dune-2021" }, score: 4, review_text: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
      ],
      total: 25,
      page: 1,
      limit: 10,
    });

    render(await AdminUserDetailPage(buildProps("alice")));

    expect(screen.getByRole("navigation", { name: "reviews.pagination.nav" })).toBeInTheDocument();
  });
});
