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
// `fields` is exposed via `data-props` (same pattern as
// `admin/users/[username]/page.test.tsx`'s `AdminUserActionsPanel` mock) so
// `buildFields`' game developer/publisher rows (FE-61) can be asserted on
// without duplicating `ItemHero`'s own rendering tests.
vi.mock("@/components/item-hero", () => ({
  ItemHero: (props: { fields: { label: string; value: string }[] }) => (
    <div data-testid="item-hero" data-props={JSON.stringify({ fields: props.fields })} />
  ),
}));
vi.mock("@/components/item-credits", () => ({
  ItemCredits: (props: { heading: string; emptyMessage: string }) => (
    <div
      data-testid="item-credits"
      data-heading={props.heading}
      data-empty-message={props.emptyMessage}
    />
  ),
}));
vi.mock("@/components/item-platforms", () => ({
  ItemPlatforms: (props: {
    platforms: { id: number; name: string; slug: string }[];
    heading: string;
    emptyMessage: string;
  }) => (
    <div
      data-testid="item-platforms"
      data-platforms={JSON.stringify(props.platforms)}
      data-heading={props.heading}
      data-empty-message={props.emptyMessage}
    />
  ),
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

const gameItem = {
  id: 10,
  title: "Hades",
  original_title: null,
  slug: "hades",
  overview: "A roguelike dungeon crawler.",
  release_date: "2020-09-17",
  game_type: "MAIN_GAME",
  original_language: null,
  poster_url: "https://images.example/hades.jpg",
  backdrop_url: null,
  rating_external: 9.3,
  rating_count_external: 500,
  rating_internal: null,
  rating_count_internal: 0,
  genres: [],
  platforms: [],
  credits: [],
  companies: [],
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

describe("ItemDetailPage — game developer/publisher fields (FE-61)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
  });

  function fieldsFromDom(container: HTMLElement): { label: string; value: string }[] {
    const hero = container.querySelector('[data-testid="item-hero"]');
    expect(hero).not.toBeNull();
    const props = JSON.parse(hero?.getAttribute("data-props") ?? "{}");
    return props.fields;
  }

  it("shows developer and publisher as distinct fields when both are present", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...gameItem,
        companies: [
          { id: 1, name: "Supergiant Games", slug: "supergiant-games", role: "DEVELOPER" },
          { id: 1, name: "Supergiant Games", slug: "supergiant-games", role: "PUBLISHER" },
        ],
      },
    });

    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));

    const fields = fieldsFromDom(container);
    expect(fields).toContainEqual({ label: "fields.developer", value: "Supergiant Games" });
    expect(fields).toContainEqual({ label: "fields.publisher", value: "Supergiant Games" });
  });

  it("joins multiple companies with the same role instead of dropping any", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...gameItem,
        companies: [
          { id: 1, name: "Nintendo EPD", slug: "nintendo-epd", role: "DEVELOPER" },
          { id: 2, name: "Nintendo", slug: "nintendo", role: "PUBLISHER" },
          { id: 3, name: "The Pokémon Company", slug: "the-pokemon-company", role: "PUBLISHER" },
        ],
      },
    });

    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));

    const fields = fieldsFromDom(container);
    expect(fields).toContainEqual({ label: "fields.developer", value: "Nintendo EPD" });
    expect(fields).toContainEqual({
      label: "fields.publisher",
      value: "Nintendo, The Pokémon Company",
    });
  });

  it("shows the developer field with its value and the publisher field with the placeholder when there's no publisher (FE-63)", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...gameItem,
        companies: [
          { id: 1, name: "Indie Studio", slug: "indie-studio", role: "DEVELOPER" },
        ],
      },
    });

    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));

    const fields = fieldsFromDom(container);
    expect(fields).toContainEqual({ label: "fields.developer", value: "Indie Studio" });
    expect(fields).toContainEqual({
      label: "fields.publisher",
      value: "fields.notAvailable",
    });
  });

  it("shows both fields with the not-available placeholder when the game has no known companies (FE-63)", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...gameItem, companies: [] },
    });

    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));

    const fields = fieldsFromDom(container);
    expect(fields).toContainEqual({
      label: "fields.developer",
      value: "fields.notAvailable",
    });
    expect(fields).toContainEqual({
      label: "fields.publisher",
      value: "fields.notAvailable",
    });
  });
});

describe("ItemDetailPage — game_type translated to a human label, not the raw IGDB enum name (FE-58)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
  });

  function fieldsFromDom(container: HTMLElement): { label: string; value: string }[] {
    const hero = container.querySelector('[data-testid="item-hero"]');
    expect(hero).not.toBeNull();
    const props = JSON.parse(hero?.getAttribute("data-props") ?? "{}");
    return props.fields;
  }

  it.each([
    "MAIN_GAME",
    "DLC_ADDON",
    "EXPANSION",
    "BUNDLE",
    "STANDALONE_EXPANSION",
    "MOD",
    "EPISODE",
    "SEASON",
    "REMAKE",
    "REMASTER",
    "EXPANDED_GAME",
    "PORT",
    "FORK",
    "PACK",
    "UPDATE",
  ])("looks up ItemDetail.gameTypes.%s instead of showing the raw code", async (code) => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...gameItem, game_type: code },
    });

    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));

    expect(fieldsFromDom(container)).toContainEqual({
      label: "fields.gameType",
      value: `gameTypes.${code}`,
    });
  });

  it("falls back to gameTypes.other for a category outside the known 15 (e.g. a future IGDB addition) instead of crashing or showing the raw value", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...gameItem, game_type: "SPINOFF" },
    });

    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));

    expect(fieldsFromDom(container)).toContainEqual({
      label: "fields.gameType",
      value: "gameTypes.other",
    });
  });

  it("still shows the not-available placeholder (not gameTypes.other) when game_type itself is absent", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...gameItem, game_type: null },
    });

    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));

    expect(fieldsFromDom(container)).toContainEqual({
      label: "fields.gameType",
      value: "fields.notAvailable",
    });
  });
});

describe("ItemDetailPage — not-available placeholder for absent metadata fields (FE-63)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
  });

  function fieldsFromDom(container: HTMLElement): { label: string; value: string }[] {
    const hero = container.querySelector('[data-testid="item-hero"]');
    expect(hero).not.toBeNull();
    const props = JSON.parse(hero?.getAttribute("data-props") ?? "{}");
    return props.fields;
  }

  it("movie: shows the actual value when present and the placeholder when absent (no originalLanguage row at all, FE-64)", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: movieItem });
    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));
    expect(fieldsFromDom(container)).toContainEqual({
      label: "fields.releaseDate",
      value: "2021-10-22",
    });
    expect(fieldsFromDom(container)).not.toContainEqual(
      expect.objectContaining({ label: "fields.originalLanguage" }),
    );

    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...movieItem, release_date: null },
    });
    const { container: container2 } = render(
      await ItemDetailPage(buildProps("movie", "dune-2021")),
    );
    expect(fieldsFromDom(container2)).toContainEqual({
      label: "fields.releaseDate",
      value: "fields.notAvailable",
    });
  });

  it("movie: a real runtime of 0 is shown formatted, not as the placeholder", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...movieItem, runtime: 0 },
    });
    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));
    expect(fieldsFromDom(container)).toContainEqual({
      label: "fields.runtime",
      value: 'fields.runtimeValue:{"minutes":0}',
    });
  });

  it("movie: a missing runtime shows the placeholder instead of a formatted value", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...movieItem, runtime: null },
    });
    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));
    expect(fieldsFromDom(container)).toContainEqual({
      label: "fields.runtime",
      value: "fields.notAvailable",
    });
  });

  it("series: shows the actual season count when present, including a legitimate 0", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        first_air_date: "2021-01-01",
        last_air_date: "2021-03-01",
        number_of_seasons: 0,
        status: "Upcoming",
      },
    });
    const { container } = render(await ItemDetailPage(buildProps("series", "some-series")));
    expect(fieldsFromDom(container)).toContainEqual({ label: "fields.seasons", value: "0" });
  });

  it("series: shows the placeholder for every optional field that's absent (no episodes/originalLanguage row at all, FE-64)", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        release_date: undefined,
        first_air_date: null,
        last_air_date: null,
        number_of_seasons: null,
        number_of_episodes: null,
        status: null,
        original_language: null,
      },
    });
    const { container } = render(await ItemDetailPage(buildProps("series", "some-series")));
    const fields = fieldsFromDom(container);
    expect(fields).toContainEqual({ label: "fields.firstAirDate", value: "fields.notAvailable" });
    expect(fields).toContainEqual({ label: "fields.seasons", value: "fields.notAvailable" });
    expect(fields).toContainEqual({ label: "fields.status", value: "fields.notAvailable" });
    expect(fields).not.toContainEqual(expect.objectContaining({ label: "fields.episodes" }));
    expect(fields).not.toContainEqual(
      expect.objectContaining({ label: "fields.originalLanguage" }),
    );
  });

  it("movie: shows the director (role DIRECTOR in credits) with a value and with the placeholder (FE-64)", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        credits: [
          { role: "DIRECTOR", person_name: "Denis Villeneuve", person_slug: "denis-villeneuve" },
        ],
      },
    });
    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));
    expect(fieldsFromDom(container)).toContainEqual({
      label: "fields.director",
      value: "Denis Villeneuve",
    });

    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
    getItemDetail.mockResolvedValue({ status: "ok", item: { ...movieItem, credits: [] } });
    const { container: container2 } = render(
      await ItemDetailPage(buildProps("movie", "dune-2021")),
    );
    expect(fieldsFromDom(container2)).toContainEqual({
      label: "fields.director",
      value: "fields.notAvailable",
    });
  });

  it("series: shows the creator (role CREATOR in credits) with a value and with the placeholder (FE-64)", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        release_date: undefined,
        first_air_date: "2021-01-01",
        credits: [{ role: "CREATOR", person_name: "Vince Gilligan", person_slug: "vince-gilligan" }],
      },
    });
    const { container } = render(await ItemDetailPage(buildProps("series", "some-series")));
    expect(fieldsFromDom(container)).toContainEqual({
      label: "fields.creator",
      value: "Vince Gilligan",
    });

    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...movieItem, release_date: undefined, first_air_date: "2021-01-01", credits: [] },
    });
    const { container: container2 } = render(
      await ItemDetailPage(buildProps("series", "some-series")),
    );
    expect(fieldsFromDom(container2)).toContainEqual({
      label: "fields.creator",
      value: "fields.notAvailable",
    });
  });

  it("book: shows the actual value when present and the placeholder when absent (no originalLanguage row — Open Library never has it at work level, FE-64)", async () => {
    const bookItem = {
      ...movieItem,
      release_date: undefined,
      first_publish_date: "1965-08-01",
      original_language: "en",
      isbn: "9780441013593",
      credits: [{ role: "AUTHOR", person_name: "Frank Herbert", person_slug: "frank-herbert" }],
    };
    getItemDetail.mockResolvedValue({ status: "ok", item: bookItem });
    const { container } = render(await ItemDetailPage(buildProps("book", "dune-1965")));
    const fields = fieldsFromDom(container);
    expect(fields).toContainEqual({
      label: "fields.firstPublishDate",
      value: "1965-08-01",
    });
    expect(fields).toContainEqual({ label: "fields.author", value: "Frank Herbert" });
    expect(fields).toContainEqual({ label: "fields.isbn", value: "9780441013593" });
    expect(fields).not.toContainEqual(
      expect.objectContaining({ label: "fields.originalLanguage" }),
    );

    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...bookItem,
        first_publish_date: null,
        original_language: null,
        isbn: null,
        credits: [],
      },
    });
    const { container: container2 } = render(
      await ItemDetailPage(buildProps("book", "dune-1965")),
    );
    const fields2 = fieldsFromDom(container2);
    expect(fields2).toContainEqual({
      label: "fields.firstPublishDate",
      value: "fields.notAvailable",
    });
    expect(fields2).toContainEqual({ label: "fields.author", value: "fields.notAvailable" });
    expect(fields2).toContainEqual({ label: "fields.isbn", value: "fields.notAvailable" });
    expect(fields2).not.toContainEqual(
      expect.objectContaining({ label: "fields.originalLanguage" }),
    );
  });

  it("game: shows the actual value when present and the placeholder when absent (gameType — platforms is no longer one of these label/value rows, see FE-60 below; no originalLanguage row — IGDB has no such concept, FE-64)", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...gameItem, platforms: [{ id: 1, name: "PC", slug: "pc" }] },
    });
    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));
    expect(fieldsFromDom(container)).not.toContainEqual(
      expect.objectContaining({ label: "fields.platforms" }),
    );
    expect(fieldsFromDom(container)).not.toContainEqual(
      expect.objectContaining({ label: "fields.originalLanguage" }),
    );

    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...gameItem, platforms: [], game_type: null, original_language: null },
    });
    const { container: container2 } = render(await ItemDetailPage(buildProps("game", "hades")));
    const fields = fieldsFromDom(container2);
    expect(fields).toContainEqual({ label: "fields.gameType", value: "fields.notAvailable" });
    expect(fields).not.toContainEqual(
      expect.objectContaining({ label: "fields.originalLanguage" }),
    );
  });
});

describe("ItemDetailPage — field order follows docs/detail-page-layout.md (FE-64)", () => {
  // Every other test in this file uses `toContainEqual`, which is
  // order-insensitive by design (it's checking presence/placeholder
  // behavior, not sequence) — so none of them would catch a `buildFields`
  // push reordered or misplaced. `ItemHero` renders `fields.map(...)`
  // directly (`item-hero.tsx`), so array order IS render order; these use
  // `toEqual` against the full array to actually pin that order down.
  function fieldsFromDom(container: HTMLElement): { label: string; value: string }[] {
    const hero = container.querySelector('[data-testid="item-hero"]');
    expect(hero).not.toBeNull();
    const props = JSON.parse(hero?.getAttribute("data-props") ?? "{}");
    return props.fields;
  }

  beforeEach(() => {
    getSimilarItems.mockResolvedValue([]);
  });

  it("movie: releaseDate, director, status, runtime — in that order, no originalLanguage row", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        credits: [
          { role: "DIRECTOR", person_name: "Denis Villeneuve", person_slug: "denis-villeneuve" },
        ],
      },
    });
    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));
    expect(fieldsFromDom(container)).toEqual([
      { label: "fields.releaseDate", value: "2021-10-22" },
      { label: "fields.director", value: "Denis Villeneuve" },
      { label: "fields.status", value: "Released" },
      { label: "fields.runtime", value: 'fields.runtimeValue:{"minutes":155}' },
    ]);
  });

  it("series: firstAirDate, creator, status, seasons — in that order, no lastAirDate/episodes/originalLanguage row", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        release_date: undefined,
        first_air_date: "2011-04-17",
        last_air_date: "2019-05-19",
        number_of_seasons: 8,
        number_of_episodes: 73,
        status: "Ended",
        credits: [{ role: "CREATOR", person_name: "Vince Gilligan", person_slug: "vince-gilligan" }],
      },
    });
    const { container } = render(await ItemDetailPage(buildProps("series", "some-series")));
    expect(fieldsFromDom(container)).toEqual([
      { label: "fields.firstAirDate", value: "2011-04-17" },
      { label: "fields.creator", value: "Vince Gilligan" },
      { label: "fields.status", value: "Ended" },
      { label: "fields.seasons", value: "8" },
    ]);
  });

  it("book: firstPublishDate, author, isbn — in that order, no originalLanguage row", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...movieItem,
        release_date: undefined,
        first_publish_date: "1965-08-01",
        isbn: "9780441013593",
        credits: [{ role: "AUTHOR", person_name: "Frank Herbert", person_slug: "frank-herbert" }],
      },
    });
    const { container } = render(await ItemDetailPage(buildProps("book", "dune-1965")));
    expect(fieldsFromDom(container)).toEqual([
      { label: "fields.firstPublishDate", value: "1965-08-01" },
      { label: "fields.author", value: "Frank Herbert" },
      { label: "fields.isbn", value: "9780441013593" },
    ]);
  });

  it("game: releaseDate, developer, publisher, gameType — in that order, no originalLanguage row", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: {
        ...gameItem,
        original_language: "en",
        companies: [
          { id: 1, name: "Supergiant Games", slug: "supergiant-games", role: "DEVELOPER" },
          { id: 2, name: "Some Publisher", slug: "some-publisher", role: "PUBLISHER" },
        ],
      },
    });
    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));
    expect(fieldsFromDom(container)).toEqual([
      { label: "fields.releaseDate", value: "2020-09-17" },
      { label: "fields.developer", value: "Supergiant Games" },
      { label: "fields.publisher", value: "Some Publisher" },
      { label: "fields.gameType", value: "gameTypes.MAIN_GAME" },
    ]);
  });
});

describe("ItemDetailPage — 'Credits' section (full cast/crew) only renders for movie/series (FE-64)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
  });

  it("movie/series render it with the generic 'Credits' heading", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: movieItem });
    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));
    const credits = container.querySelector('[data-testid="item-credits"]');
    expect(credits).not.toBeNull();
    expect(credits?.getAttribute("data-heading")).toBe("credits.heading");
    expect(credits?.getAttribute("data-empty-message")).toBe("credits.empty");
  });

  it("book renders no 'Credits' section at all — the single author already has its own row in the fields dl", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...movieItem, release_date: undefined, first_publish_date: "1965-08-01" },
    });
    const { container } = render(await ItemDetailPage(buildProps("book", "dune-1965")));
    expect(container.querySelector('[data-testid="item-credits"]')).toBeNull();
  });

  it("game renders no 'Credits' section at all — developer/publisher already cover it in the fields dl", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: gameItem });
    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));
    expect(container.querySelector('[data-testid="item-credits"]')).toBeNull();
  });
});

describe("ItemDetailPage — ItemPlatforms renders for game only, in its own section (FE-60/FE-64)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
  });

  it("forwards GameOut.platforms verbatim for a game, with the platforms heading/empty copy", async () => {
    const platforms = [
      { id: 1, name: "PlayStation 5", slug: "ps5" },
      { id: 2, name: "Nintendo Switch", slug: "switch" },
    ];
    getItemDetail.mockResolvedValue({ status: "ok", item: { ...gameItem, platforms } });

    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));

    const el = container.querySelector('[data-testid="item-platforms"]');
    expect(el).not.toBeNull();
    expect(JSON.parse(el?.getAttribute("data-platforms") ?? "null")).toEqual(platforms);
    expect(el?.getAttribute("data-heading")).toBe("platformsLabel");
    expect(el?.getAttribute("data-empty-message")).toBe("platformsEmpty");
  });

  it("renders no ItemPlatforms section at all for movie/series/book", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: movieItem });
    const { container: movieContainer } = render(
      await ItemDetailPage(buildProps("movie", "dune-2021")),
    );
    expect(movieContainer.querySelector('[data-testid="item-platforms"]')).toBeNull();

    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...movieItem, release_date: undefined, first_publish_date: "1965-08-01" },
    });
    const { container: bookContainer } = render(
      await ItemDetailPage(buildProps("book", "dune-1965")),
    );
    expect(bookContainer.querySelector('[data-testid="item-platforms"]')).toBeNull();
  });
});

describe("ItemDetailPage — Credits/Platforms sit right after the hero, before 'Your rating'/'Reviews' (FE-64)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSimilarItems.mockResolvedValue([]);
  });

  function testIdOrder(container: HTMLElement): string[] {
    return Array.from(
      container.querySelectorAll(
        '[data-testid="item-hero"], [data-testid="item-credits"], [data-testid="item-platforms"], [data-testid="rating-widget"], [data-testid="item-reviews"], [data-testid="item-similar"]',
      ),
    ).map((el) => el.getAttribute("data-testid") as string);
  }

  it("movie: hero, credits, rating-widget, reviews, similar — in that order", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: movieItem });
    const { container } = render(await ItemDetailPage(buildProps("movie", "dune-2021")));
    expect(testIdOrder(container)).toEqual([
      "item-hero",
      "item-credits",
      "rating-widget",
      "item-reviews",
      "item-similar",
    ]);
  });

  it("game: hero, platforms, rating-widget, reviews, similar — in that order", async () => {
    getItemDetail.mockResolvedValue({ status: "ok", item: gameItem });
    const { container } = render(await ItemDetailPage(buildProps("game", "hades")));
    expect(testIdOrder(container)).toEqual([
      "item-hero",
      "item-platforms",
      "rating-widget",
      "item-reviews",
      "item-similar",
    ]);
  });

  it("book: hero, rating-widget, reviews, similar — no credits/platforms slot at all", async () => {
    getItemDetail.mockResolvedValue({
      status: "ok",
      item: { ...movieItem, release_date: undefined, first_publish_date: "1965-08-01" },
    });
    const { container } = render(await ItemDetailPage(buildProps("book", "dune-1965")));
    expect(testIdOrder(container)).toEqual([
      "item-hero",
      "rating-widget",
      "item-reviews",
      "item-similar",
    ]);
  });
});
