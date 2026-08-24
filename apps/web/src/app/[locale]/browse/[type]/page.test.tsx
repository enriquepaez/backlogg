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

// `@/lib/catalog` transitively imports `server-only` (via
// `@/lib/auth/session`) — mocked wholesale, same rationale as the sibling
// `[type]/[slug]/page.test.tsx`.
const listCatalog = vi.fn();
const getGenres = vi.fn();
const CATALOG_TYPES = ["movie", "series", "book", "game"];
vi.mock("@/lib/catalog", () => ({
  CATALOG_SORTS: ["rating_desc", "rating_asc", "date_desc", "date_asc", "title_asc"],
  DEFAULT_CATALOG_SORT: "rating_desc",
  isCatalogType: (value: string) => CATALOG_TYPES.includes(value),
  listCatalog: (type: string, query: unknown) => listCatalog(type, query),
  getGenres: (type: string) => getGenres(type),
}));

const { generateMetadata } = await import("./page");

function buildProps(type: string, locale = "en") {
  return {
    params: Promise.resolve({ locale, type }),
    searchParams: Promise.resolve({}),
  };
}

describe("generateMetadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns {} for an invalid type", async () => {
    const metadata = await generateMetadata(buildProps("not-a-type"));

    expect(metadata).toEqual({});
  });

  it("sets an autocanonical URL with no query params", async () => {
    const metadata = await generateMetadata(buildProps("movie"));

    expect(metadata.alternates).toEqual({ canonical: "/en/browse/movie" });
  });

  it("builds the canonical from the actual locale/type params, ignoring genre/sort/page", async () => {
    const metadata = await generateMetadata({
      params: Promise.resolve({ locale: "es", type: "book" }),
      searchParams: Promise.resolve({ genre: "fantasy", sort: "date_desc", page: "3" }),
    });

    expect(metadata.alternates).toEqual({ canonical: "/es/browse/book" });
  });
});
