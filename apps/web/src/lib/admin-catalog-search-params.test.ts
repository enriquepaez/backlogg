import { describe, expect, it } from "vitest";

import {
  parseAdminCatalogDateFrom,
  parseAdminCatalogDateTo,
  parseAdminCatalogGenre,
  parseAdminCatalogPage,
  parseAdminCatalogRatingExternalMax,
  parseAdminCatalogRatingExternalMin,
  parseAdminCatalogRatingInternalMax,
  parseAdminCatalogRatingInternalMin,
  parseAdminCatalogSearch,
  parseAdminCatalogSort,
} from "./admin-catalog-search-params";

describe("parseAdminCatalogGenre", () => {
  it("returns the value as-is when present", () => {
    expect(parseAdminCatalogGenre("action")).toBe("action");
  });

  it("returns undefined when absent or empty", () => {
    expect(parseAdminCatalogGenre(undefined)).toBeUndefined();
    expect(parseAdminCatalogGenre("")).toBeUndefined();
  });

  it("uses the first value of an array param", () => {
    expect(parseAdminCatalogGenre(["action", "drama"])).toBe("action");
  });
});

describe("parseAdminCatalogSort", () => {
  it("returns a recognized sort as-is", () => {
    expect(parseAdminCatalogSort("title_asc")).toBe("title_asc");
  });

  it("falls back to the default sort for missing/unrecognized values", () => {
    expect(parseAdminCatalogSort(undefined)).toBe("rating_desc");
    expect(parseAdminCatalogSort("bogus")).toBe("rating_desc");
  });
});

describe("parseAdminCatalogPage", () => {
  it("parses a positive integer", () => {
    expect(parseAdminCatalogPage("3")).toBe(3);
  });

  it("falls back to 1 for missing/invalid/non-positive values", () => {
    expect(parseAdminCatalogPage(undefined)).toBe(1);
    expect(parseAdminCatalogPage("bogus")).toBe(1);
    expect(parseAdminCatalogPage("-3")).toBe(1);
    expect(parseAdminCatalogPage("0")).toBe(1);
  });
});

describe("parseAdminCatalogSearch", () => {
  it("trims and returns a non-empty value", () => {
    expect(parseAdminCatalogSearch("  dune  ")).toBe("dune");
  });

  it("returns undefined when absent, empty, or whitespace-only", () => {
    expect(parseAdminCatalogSearch(undefined)).toBeUndefined();
    expect(parseAdminCatalogSearch("")).toBeUndefined();
    expect(parseAdminCatalogSearch("   ")).toBeUndefined();
  });

  it("uses the first value of an array param", () => {
    expect(parseAdminCatalogSearch(["dune", "hades"])).toBe("dune");
  });
});

describe("parseAdminCatalogDateFrom / parseAdminCatalogDateTo", () => {
  it("accepts a well-formed ISO date", () => {
    expect(parseAdminCatalogDateFrom("2020-01-01")).toBe("2020-01-01");
    expect(parseAdminCatalogDateTo("2021-12-31")).toBe("2021-12-31");
  });

  it("rejects a malformed string", () => {
    expect(parseAdminCatalogDateFrom("not-a-date")).toBeUndefined();
    expect(parseAdminCatalogDateFrom("2020/01/01")).toBeUndefined();
    expect(parseAdminCatalogDateFrom("20-01-01")).toBeUndefined();
  });

  it("rejects a shape-valid but nonexistent calendar date", () => {
    expect(parseAdminCatalogDateFrom("2024-02-30")).toBeUndefined();
    expect(parseAdminCatalogDateFrom("2024-13-01")).toBeUndefined();
  });

  it("returns undefined when absent", () => {
    expect(parseAdminCatalogDateFrom(undefined)).toBeUndefined();
    expect(parseAdminCatalogDateTo(undefined)).toBeUndefined();
  });
});

describe("rating range parsers", () => {
  it("parses a finite number", () => {
    expect(parseAdminCatalogRatingInternalMin("3")).toBe(3);
    expect(parseAdminCatalogRatingInternalMax("4.5")).toBe(4.5);
    expect(parseAdminCatalogRatingExternalMin("6.5")).toBe(6.5);
    expect(parseAdminCatalogRatingExternalMax("9")).toBe(9);
  });

  it("returns undefined for missing/non-numeric values", () => {
    expect(parseAdminCatalogRatingInternalMin(undefined)).toBeUndefined();
    expect(parseAdminCatalogRatingInternalMin("not-a-number")).toBeUndefined();
    expect(parseAdminCatalogRatingExternalMax("")).toBeUndefined();
  });
});
