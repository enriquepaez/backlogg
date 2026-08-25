import { describe, expect, it } from "vitest";

import { GAME_TYPE_CODES, gameTypeLabel } from "./game-type-labels";

/** Echoes the key back — same fake-translator convention used throughout
 * `apps/web` tests (e.g. `page.test.tsx`'s `next-intl/server` mock) so
 * assertions can check the exact i18n key that was looked up. */
const t = (key: string) => key;

describe("gameTypeLabel", () => {
  it.each(GAME_TYPE_CODES)(
    "translates the %s IGDB category via ItemDetail.gameTypes.<code>",
    (code) => {
      expect(gameTypeLabel(code, t)).toBe(`gameTypes.${code}`);
    },
  );

  it("covers all 15 GAME_TYPE_MAP entries from backlogg/games/constants.py, not just the 8 ingestable ones", () => {
    expect(GAME_TYPE_CODES).toHaveLength(15);
    // The 7 categories `ALLOWED_GAME_TYPES` (backend feature
    // `game_category_allowlist`) excludes from ingestion — historical rows
    // tagged with one of these must still translate, not crash/fall through.
    for (const excluded of ["BUNDLE", "MOD", "EXPANDED_GAME", "PORT", "FORK", "PACK", "UPDATE"]) {
      expect(GAME_TYPE_CODES).toContain(excluded);
    }
  });

  it("falls back to gameTypes.other for a value outside the known IGDB codes (e.g. a future category IGDB adds later)", () => {
    expect(gameTypeLabel("SPINOFF", t)).toBe("gameTypes.other");
  });

  it("falls back to gameTypes.other for an empty string rather than crashing or rendering blank", () => {
    expect(gameTypeLabel("", t)).toBe("gameTypes.other");
  });

  it("is case-sensitive — a lowercase variant of a known code is treated as unrecognized", () => {
    expect(gameTypeLabel("main_game", t)).toBe("gameTypes.other");
  });
});
