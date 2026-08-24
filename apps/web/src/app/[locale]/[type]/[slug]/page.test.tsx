import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Same `next-intl/server` mocking approach as
// `admin/users/[username]/page.test.tsx` — `t(key, vars)` echoes as
// `key:{"var":"value"}` when vars are given.
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

vi.mock("@/lib/env", () => ({
  env: { SITE_URL: "https://backlogg.example" },
}));

const getItemDetail = vi.fn();
const getSimilarItems = vi.fn();
const CATALOG_TYPES = ["movie", "series", "book", "game"];
vi.mock("@/lib/catalog", () => ({
  getItemDetail: (type: string, slug: string) => getItemDetail(type, slug),
  getSimilarItems: (type: string, slug: string) => getSimilarItems(type, slug),
  isCatalogType: (value: string) => CATALOG_TYPES.includes(value),
}));

// `ItemHero`/`ItemCredits`/`ItemReviews`/`ItemSimilar`/`RatingWidget` are all
// presentational Client/Server Components with their own tests — out of
// scope here (same rationale `admin/users/[username]/page.test.tsx` uses for
// `AdminUserActionsPanel`/`UserReviewCard`), stubbed to keep this file
// focused on `generateMetadata`'s `alternates.canonical` and the JSON-LD
// `<script>` (FE-53).
vi.mock("@/components/item-hero", () => ({
  ItemHero: () => <div data-testid="item-hero" />,
}));
vi.mock("@/components/item-credits", () => ({
  ItemCredits: () => <div data-testid="item-credits" />,
}));
vi.mock("@/components/item-reviews", () => ({
  ItemReviews: () => <div data-testid="item-reviews" />,
}));
vi.mock("@/components/item-similar", () => ({
  ItemSimilar: () => <div data-testid="item-similar" />,
}));
vi.mock("@/components/rating-widget", () => ({
  RatingWidget: () => <div data-testid="rating-widget" />,
}));

const { default: ItemDetailPage, generateMetadata } = await import("./page");

const movieItem = {
  id: 1,
  title: "Dune",
  original_title: null,
  slug: "dune-2021",
  overview: "A duke's son leads a rebellion.",
  release_date: "2021-10-22",
  runtime: 155,
  original_language: "en",
  poster_url: "https://images.example/dune.jpg",
  backdrop_url: null,
  budget: null,
  revenue: null,
  status: "Released",
  rating_external: 8.1,
  rating_count_external: 1000,
  rating_internal: 4.5,
  rating_count_internal: 12,
  genres: [],
  credits: [],
  viewer_status: null,
};

function buildProps(type: string, slug: string, locale = "en") {
  return {
    params: Promise.resolve({ locale, type, slug }),
    searchParams: Promise.resolve({}),
  };
}

describe("generateMetadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns {} for an invalid type", async () => {
    const metadata = await generateMetadata(buildProps("not-a-type", "dune-2021"));
    expect(metadata).toEqual({});
    expect(getItemDetail).not.toHaveBeenCalled();
  });

  it("returns {} when the item lookup doesn't resolve", async () => {
    getItemDetail.mockResolvedValue({ status: "not-found" });

    const metadata = await generateMetadata(buildProps("movie", "ghost"));

    expect(metadata).toEqual({});
  });

  it("sets an autocanonical URL with no query params", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: movieItem });

    const metadata = await generateMetadata(buildProps("movie", "dune-2021"));

    expect(metadata.alternates).toEqual({ canonical: "/en/movie/dune-2021" });
  });

  it("builds the canonical from the actual locale/type/slug params", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: movieItem });

    const metadata = await generateMetadata(buildProps("book", "dune-1965", "es"));

    expect(metadata.alternates).toEqual({ canonical: "/es/book/dune-1965" });
  });
});

describe("ItemDetailPage — JSON-LD", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
  });

  function jsonLdFromDom(container: HTMLElement): Record<string, unknown> {
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    return JSON.parse(script?.innerHTML ?? "{}");
  }

  it("renders a Movie JSON-LD script with image, date and aggregate rating", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: movieItem });

    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));

    const jsonLd = jsonLdFromDom(container);
    expect(jsonLd).toMatchObject({
      "@context": "https://schema.org",
      "@type": "Movie",
      name: "Dune",
      url: "https://backlogg.example/en/movie/dune-2021",
      image: "https://images.example/dune.jpg",
      datePublished: "2021-10-22",
      aggregateRating: {
        "@type": "AggregateRating",
        ratingValue: 4.5,
        ratingCount: 12,
        bestRating: 5,
        worstRating: 1,
      },
    });
  });

  it("maps series/book/game to TVSeries/Book/VideoGame respectively", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        release_date: undefined,
        first_air_date: "2021-01-01",
        credits: [],
      },
    });

    const { container } = render(await ItemDetailPage(buildProps("series", "some-series")));

    expect(jsonLdFromDom(container)).toMatchObject({
      "@type": "TVSeries",
      datePublished: "2021-01-01",
    });
  });

  it("omits image/date/aggregateRating fields that are absent", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        poster_url: null,
        release_date: null,
        rating_internal: null,
        rating_count_internal: 0,
      },
    });

    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));

    const jsonLd = jsonLdFromDom(container);
    expect(jsonLd).not.toHaveProperty("image");
    expect(jsonLd).not.toHaveProperty("datePublished");
    expect(jsonLd).not.toHaveProperty("aggregateRating");
  });

  it("does not render JSON-LD when the item is not found", async () => {
    getItemDetail.mockResolvedValue({ status: "not-found" });

    await expect(ItemDetailPage(buildProps("movie", "ghost"))).rejects.toThrow();

    expect(notFound).toHaveBeenCalled();
  });

  it("does not render JSON-LD on a transient fetch error", async () => {
    getItemDetail.mockResolvedValue({ status: "error" });

    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));

    expect(container.querySelector('script[type="application/ld+json"]')).toBeNull();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
