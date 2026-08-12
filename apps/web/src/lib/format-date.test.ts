import { describe, expect, it } from "vitest";

import { formatDate } from "./format-date";

describe("formatDate", () => {
  it("formats an ISO date-time string in the given locale", () => {
    expect(formatDate("2026-01-01T00:00:00Z", "en")).toBe("January 1, 2026");
  });

  it("formats the same instant in a different locale", () => {
    expect(formatDate("2026-01-01T00:00:00Z", "es")).toBe("1 de enero de 2026");
  });

  it("pins to UTC regardless of the time-of-day component, so a date near midnight UTC never shifts to an adjacent day", () => {
    // 23:30 UTC on Jan 1st: in a timezone west of UTC (e.g. local -05:00)
    // this would render as Jan 1st too, but a naive local-timezone
    // formatter running east of UTC could push it to Jan 2nd. Pinning to
    // `timeZone: "UTC"` keeps it deterministic regardless of where the
    // code runs.
    expect(formatDate("2026-01-01T23:30:00Z", "en")).toBe("January 1, 2026");
  });
});
