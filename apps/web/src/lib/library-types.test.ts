import { describe, expect, it } from "vitest";

import {
  DEFAULT_LIBRARY_SORT,
  isLibrarySort,
  LIBRARY_SORTS,
  reviewScoreKey,
  sortLibraryEntries,
  type LibraryEntry,
} from "./library-types";

function entry(overrides: {
  itemType?: string;
  slug?: string;
  title?: string;
  releaseDate?: string | null;
  updatedAt?: string;
}): LibraryEntry {
  return {
    item: {
      item_type: overrides.itemType ?? "MOVIE",
      title: overrides.title ?? "Untitled",
      slug: overrides.slug ?? "untitled",
      poster_url: null,
      release_date: overrides.releaseDate ?? null,
      rating_external: null,
      rating_internal: null,
    },
    status: "want",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: overrides.updatedAt ?? "2026-01-01T00:00:00Z",
  };
}

describe("isLibrarySort", () => {
  it("accepts the four valid sort values", () => {
    for (const sort of LIBRARY_SORTS) {
      expect(isLibrarySort(sort)).toBe(true);
    }
  });

  it("rejects anything else, including a CatalogSort value", () => {
    expect(isLibrarySort("rating_desc_bogus")).toBe(false);
    expect(isLibrarySort("")).toBe(false);
  });
});

describe("DEFAULT_LIBRARY_SORT", () => {
  it("is 'updated_desc'", () => {
    expect(DEFAULT_LIBRARY_SORT).toBe("updated_desc");
  });
});

describe("reviewScoreKey", () => {
  it("uppercases item_type and pairs it with the slug", () => {
    expect(reviewScoreKey("movie", "dune-2021")).toBe("MOVIE:dune-2021");
    expect(reviewScoreKey("MOVIE", "dune-2021")).toBe("MOVIE:dune-2021");
  });
});

describe("sortLibraryEntries", () => {
  it("does not mutate the input array", () => {
    const entries = [entry({ title: "B" }), entry({ title: "A" })];
    const original = [...entries];

    sortLibraryEntries(entries, "title_asc");

    expect(entries).toEqual(original);
  });

  it("title_asc sorts alphabetically", () => {
    const entries = [entry({ title: "Zelda" }), entry({ title: "Astro Bot" }), entry({ title: "Mario" })];

    const sorted = sortLibraryEntries(entries, "title_asc");

    expect(sorted.map((e) => e.item.title)).toEqual(["Astro Bot", "Mario", "Zelda"]);
  });

  it("date_desc sorts by release date, newest first, missing dates last", () => {
    const entries = [
      entry({ title: "old", releaseDate: "1999-03-31" }),
      entry({ title: "no-date", releaseDate: null }),
      entry({ title: "new", releaseDate: "2021-10-22" }),
    ];

    const sorted = sortLibraryEntries(entries, "date_desc");

    expect(sorted.map((e) => e.item.title)).toEqual(["new", "old", "no-date"]);
  });

  it("updated_desc (default) sorts by updated_at, most recent first", () => {
    const entries = [
      entry({ title: "oldest", updatedAt: "2026-01-01T00:00:00Z" }),
      entry({ title: "newest", updatedAt: "2026-03-01T00:00:00Z" }),
      entry({ title: "middle", updatedAt: "2026-02-01T00:00:00Z" }),
    ];

    const sorted = sortLibraryEntries(entries, "updated_desc");

    expect(sorted.map((e) => e.item.title)).toEqual(["newest", "middle", "oldest"]);
  });

  it("rating_desc sorts by the score map, highest first, unrated/unmatched last", () => {
    const entries = [
      entry({ title: "unrated", itemType: "movie", slug: "unrated" }),
      entry({ title: "high", itemType: "movie", slug: "high" }),
      entry({ title: "low", itemType: "movie", slug: "low" }),
    ];
    const scores = new Map([
      [reviewScoreKey("movie", "high"), 5],
      [reviewScoreKey("movie", "low"), 2],
    ]);

    const sorted = sortLibraryEntries(entries, "rating_desc", scores);

    expect(sorted.map((e) => e.item.title)).toEqual(["high", "low", "unrated"]);
  });

  it("rating_desc treats a missing scores map as everything unrated (stable order)", () => {
    const entries = [entry({ title: "a" }), entry({ title: "b" })];

    const sorted = sortLibraryEntries(entries, "rating_desc");

    expect(sorted.map((e) => e.item.title)).toEqual(["a", "b"]);
  });
});
