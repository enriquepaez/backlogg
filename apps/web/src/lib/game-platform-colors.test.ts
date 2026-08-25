import { describe, expect, it } from "vitest";

import { PLATFORM_COLOR_CLASSES, platformFamily } from "./game-platform-colors";

/** Minimal `GamePlatformOut` builder — `id` doesn't affect classification. */
function platform(slug: string, name: string) {
  return { id: 1, slug, name };
}

describe("platformFamily", () => {
  it.each([
    ["ps", "PlayStation"],
    ["ps2", "PlayStation 2"],
    ["ps3", "PlayStation 3"],
    ["ps4--1", "PlayStation 4"],
    ["ps5", "PlayStation 5"],
    ["psp", "PlayStation Portable"],
    ["psvita", "PlayStation Vita"],
    ["psvr", "PlayStation VR"],
  ])("classifies %s (%s) as playstation", (slug, name) => {
    expect(platformFamily(platform(slug, name))).toBe("playstation");
  });

  it.each([
    ["xbox", "Xbox"],
    ["xbox360", "Xbox 360"],
    ["xboxone", "Xbox One"],
    ["series-x-s", "Xbox Series X|S"],
  ])("classifies %s (%s) as xbox", (slug, name) => {
    expect(platformFamily(platform(slug, name))).toBe("xbox");
  });

  it.each([
    ["3ds", "Nintendo 3DS"],
    ["new-3ds", "New Nintendo 3DS"],
    ["n64", "Nintendo 64"],
    ["nds", "Nintendo DS"],
    ["nes", "Nintendo Entertainment System"],
    ["ngc", "Nintendo GameCube"],
    ["snes", "Super Nintendo Entertainment System"],
    ["switch", "Nintendo Switch"],
    ["switch-2", "Nintendo Switch 2"],
    ["gb", "Game Boy"],
    ["gba", "Game Boy Advance"],
    ["gbc", "Game Boy Color"],
    ["wii", "Wii"],
    ["wiiu", "Wii U"],
    ["sfam", "Super Famicom"],
    ["famicom", "Family Computer"],
  ])("classifies %s (%s) as nintendo", (slug, name) => {
    expect(platformFamily(platform(slug, name))).toBe("nintendo");
  });

  it.each([
    ["win", "PC (Microsoft Windows)"],
    ["pc", "PC"],
    ["mac", "Mac"],
    ["linux", "Linux"],
    ["dos", "DOS"],
  ])("classifies %s (%s) as pc", (slug, name) => {
    expect(platformFamily(platform(slug, name))).toBe("pc");
  });

  it.each([
    ["atari2600", "Atari 2600"],
    ["arcade", "Arcade"],
    ["android", "Android"],
    ["browser", "Web browser"],
    ["stadia", "Google Stadia"],
    ["pc-8800-series", "PC-8800 Series"],
    ["pocketstation", "PocketStation"],
    ["winphone", "Windows Phone"],
  ])(
    "returns undefined for an unrecognized/retro slug %s (%s), never a broken family",
    (slug, name) => {
      expect(platformFamily(platform(slug, name))).toBeUndefined();
    },
  );

  it("returns undefined for an empty/malformed slug and name instead of throwing", () => {
    expect(platformFamily(platform("", ""))).toBeUndefined();
  });

  it("is case-insensitive on both slug and name", () => {
    expect(platformFamily(platform("PS5", "PLAYSTATION 5"))).toBe("playstation");
    expect(platformFamily(platform("XBOX", "xbox series x|s"))).toBe("xbox");
  });
});

describe("PLATFORM_COLOR_CLASSES", () => {
  it("has one entry per PlatformFamily, each pairing a background with its foreground token", () => {
    for (const classes of Object.values(PLATFORM_COLOR_CLASSES)) {
      expect(classes).toMatch(/^bg-platform-\S+ text-platform-\S+-foreground$/);
    }
  });
});
