import { describe, expect, it } from "vitest";

import { listSchema } from "./schemas";

describe("listSchema", () => {
  it("accepts a valid payload, trimming the title and optional description", () => {
    const result = listSchema.safeParse({
      title: "  Best sci-fi  ",
      description: "  My favorites  ",
      isPublic: true,
    });

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.title).toBe("Best sci-fi");
      expect(result.data.description).toBe("My favorites");
    }
  });

  it("accepts an empty/omitted description", () => {
    expect(listSchema.safeParse({ title: "Best sci-fi", isPublic: true }).success).toBe(true);
    expect(
      listSchema.safeParse({ title: "Best sci-fi", description: "", isPublic: false }).success,
    ).toBe(true);
  });

  it("rejects an empty (or whitespace-only) title", () => {
    expect(listSchema.safeParse({ title: "", isPublic: true }).success).toBe(false);
    expect(listSchema.safeParse({ title: "   ", isPublic: true }).success).toBe(false);
  });

  it("rejects a title over 200 characters", () => {
    expect(listSchema.safeParse({ title: "a".repeat(201), isPublic: true }).success).toBe(false);
  });

  it("accepts a title at exactly the 200-character bound", () => {
    expect(listSchema.safeParse({ title: "a".repeat(200), isPublic: true }).success).toBe(true);
  });

  it("rejects a description over 2000 characters", () => {
    expect(
      listSchema.safeParse({ title: "Best sci-fi", description: "a".repeat(2001), isPublic: true })
        .success,
    ).toBe(false);
  });
});
