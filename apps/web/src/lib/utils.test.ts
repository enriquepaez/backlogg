import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("joins plain class name strings", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("drops falsy values", () => {
    expect(cn("a", false, null, undefined, "b")).toBe("a b");
  });

  it("supports the conditional object syntax", () => {
    expect(cn("base", { active: true, hidden: false })).toBe("base active");
  });

  it("merges conflicting Tailwind utility classes, keeping the last one", () => {
    // twMerge's whole job: a later conflicting utility wins instead of both
    // being emitted (which is what a plain string join / clsx alone would do).
    expect(cn("px-2 py-1", "px-4")).toBe("py-1 px-4");
  });

  it("lets an explicit className override variant defaults", () => {
    expect(cn("text-sm text-muted-foreground", "text-lg")).toBe(
      "text-muted-foreground text-lg",
    );
  });
});
