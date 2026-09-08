import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import es from "../../messages/es.json";
import { CATALOG_TYPES, isCatalogType, trendingItemType } from "./catalog-types";

/**
 * Guards the trending vocabulary against the regression issue #32 was:
 * `/v1/trending` returns all four `item_type`s, the frontend only knew two,
 * and every book/game card ended up pointing at `/series/{slug}` — sometimes
 * a real, unrelated series.
 */
describe("trendingItemType", () => {
  it.each([
    ["MOVIE", "movie"],
    ["SERIES", "series"],
    ["BOOK", "book"],
    ["GAME", "game"],
  ] as const)("maps %s to the %s route segment", (itemType, expected) => {
    expect(trendingItemType({ item_type: itemType })).toBe(expected);
  });

  it("covers every type the trending endpoint can return, with no shared segment", () => {
    const segments = ["MOVIE", "SERIES", "BOOK", "GAME"].map((item_type) =>
      trendingItemType({ item_type }),
    );

    // A collapsed mapping (the issue #32 shape, `MOVIE ? movie : series`)
    // would show up here as a repeated segment.
    expect(new Set(segments).size).toBe(4);
    expect(segments).toEqual([...CATALOG_TYPES]);
  });

  it("returns undefined for an item_type outside the vocabulary instead of guessing", () => {
    // A fifth backend type (or a typo) must not silently become a series
    // link: callers skip the card on `undefined`.
    expect(trendingItemType({ item_type: "PODCAST" })).toBeUndefined();
    expect(trendingItemType({ item_type: "" })).toBeUndefined();
  });

  it("accepts only the backend's uppercase spelling shape, case-insensitively", () => {
    expect(trendingItemType({ item_type: "book" })).toBe("book");
    expect(trendingItemType({ item_type: "Book" })).toBe("book");
  });
});

describe("CATALOG_TYPES", () => {
  it("is the single four-type vocabulary shared by browse, search and trending", () => {
    expect([...CATALOG_TYPES]).toEqual(["movie", "series", "book", "game"]);
    for (const type of CATALOG_TYPES) {
      expect(isCatalogType(type)).toBe(true);
    }
  });
});

/**
 * FE-68 acceptance: "no hardcoded strings — next-intl keys in es.json and
 * en.json". Reads the message files directly so adding a type to
 * `CATALOG_TYPES` without its `/trending` filter copy (or adding it to only
 * one locale) fails here instead of rendering the raw key path in the UI.
 * Same pattern as `credit-role-labels.test.ts`.
 */
describe("Trending.filters copy", () => {
  it.each([
    ["en", en],
    ["es", es],
  ] as const)("has %s copy for every type option plus 'all'", (_locale, messages) => {
    const filters: Record<string, unknown> = messages.Trending.filters;

    expect(typeof filters.all).toBe("string");
    expect(filters.all).not.toBe("");
    for (const type of CATALOG_TYPES) {
      expect(typeof filters[type]).toBe("string");
      expect(filters[type]).not.toBe("");
    }
  });

  it("keeps es/en at parity for the whole filters block", () => {
    expect(Object.keys(es.Trending.filters).sort()).toEqual(
      Object.keys(en.Trending.filters).sort(),
    );
  });

  it("reuses /search's type vocabulary instead of forking a second one", () => {
    // Same control, same words: `Search.filters` already names all four
    // types (and "all types") in both locales.
    for (const messages of [en, es]) {
      const trending: Record<string, unknown> = messages.Trending.filters;
      const search: Record<string, unknown> = messages.Search.filters;

      expect(trending.all).toBe(search.all);
      for (const type of CATALOG_TYPES) {
        expect(trending[type]).toBe(search[type]);
      }
    }
  });

  it("no longer labels the 'all' option as movies-and-series only", () => {
    // The pre-FE-68 copy ("Películas y series" / "Movies & series") was
    // accurate when trending had two types; with four it is a lie.
    expect(es.Trending.filters.all).not.toContain("series");
    expect(en.Trending.filters.all).not.toContain("series");
  });
});
