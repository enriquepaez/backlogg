import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import es from "../../messages/es.json";
import { CATALOG_TYPES, isCatalogType, toCatalogType } from "./catalog-types";

/**
 * The single `item_type` → route-segment mapping (issue #33 unified the
 * seven copies that used to exist: `trendingItemType` here, `toCatalogType`
 * in `@/lib/search` and `library-board.tsx`, `feedItemType`,
 * `reviewItemType`, `notificationItemType` and `recommendationItemType`).
 * This suite is therefore the one place that pins the behaviour every
 * surface now depends on, and it absorbs what those modules' own suites used
 * to assert about their private copies.
 *
 * It guards two regressions:
 *
 * - issue #32 — `/v1/trending` returns all four `item_type`s, the frontend
 *   only knew two, and every book/game card ended up pointing at
 *   `/series/{slug}`, sometimes a real, unrelated series.
 * - issue #33 — `@/lib/recommendations` mapped the same field with a bare
 *   `as CatalogType` cast, so an unknown type would have produced
 *   `/{unknown}/{slug}` with nothing to catch it.
 */
describe("toCatalogType", () => {
  it.each([
    ["MOVIE", "movie"],
    ["SERIES", "series"],
    ["BOOK", "book"],
    ["GAME", "game"],
  ] as const)("maps %s to the %s route segment", (itemType, expected) => {
    expect(toCatalogType(itemType)).toBe(expected);
  });

  it("covers every type the backend can return, with no shared segment", () => {
    const segments = ["MOVIE", "SERIES", "BOOK", "GAME"].map(toCatalogType);

    // A collapsed mapping (the issue #32 shape, `MOVIE ? movie : series`)
    // would show up here as a repeated segment.
    expect(new Set(segments).size).toBe(4);
    expect(segments).toEqual([...CATALOG_TYPES]);
  });

  it("returns undefined for an item_type outside the vocabulary instead of guessing", () => {
    // A fifth backend type (or a typo) must not silently become a series
    // link, nor a `/podcast/{slug}` link: callers skip the card (or drop the
    // href) on `undefined`. `PERSON` is the one `/v1/search` really returns
    // today and the case `search.test.ts` used to own.
    expect(toCatalogType("PODCAST")).toBeUndefined();
    expect(toCatalogType("PERSON")).toBeUndefined();
    expect(toCatalogType("SHOW")).toBeUndefined();
    expect(toCatalogType("")).toBeUndefined();
  });

  it("returns undefined for a null/undefined item_type", () => {
    // `NotificationTargetOut.item_type` is nullable (`new_follower` carries
    // no target at all) — the case `notifications.test.ts` used to own via
    // the private `notificationItemType` pre-guard.
    expect(toCatalogType(null)).toBeUndefined();
    expect(toCatalogType(undefined)).toBeUndefined();
  });

  it("accepts the backend's uppercase spelling shape, case-insensitively", () => {
    expect(toCatalogType("book")).toBe("book");
    expect(toCatalogType("Book")).toBe("book");
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
