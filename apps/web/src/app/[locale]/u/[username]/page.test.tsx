import { beforeEach, describe, expect, it, vi } from "vitest";

// Same `next-intl/server` mocking approach as
// `admin/users/[username]/page.test.tsx` — `t(key, vars)` echoes as
// `key:{"var":"value"}` when vars are given.
vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string, vars?: Record<string, unknown>) =>
    vars ? `${key}:${JSON.stringify(vars)}` : key,
  setRequestLocale: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
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

vi.mock("@/lib/search", () => ({
  toCatalogType: (value: string) => value,
}));

const getUserReviews = vi.fn();
vi.mock("@/lib/user-content", () => ({
  getUserReviews: (username: string, query: unknown) => getUserReviews(username, query),
}));

const getCurrentUser = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  getCurrentUser: () => getCurrentUser(),
}));

const { generateMetadata } = await import("./page");

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
});
