import type { components } from "@backlogg/api-client";

/**
 * Slug/name -> brand-family color grouping for game platform badges (FE-60,
 * `ItemHero`'s platforms row). The dev catalog already has 70+ distinct
 * `GamePlatformOut.slug` values (IGDB's own slugs — see
 * `docs/external-apis.md`), spanning current-gen consoles down to 1980s
 * home computers. Mapping each one to its own color would be both
 * impractical (a brand-new IGDB platform must never silently break the
 * badge) and pointless (most of those differences — e.g. "Atari 2600" vs.
 * "Atari 5200" — carry no useful visual signal). Instead this groups slugs
 * into the handful of *brand families* a player actually recognizes at a
 * glance (the three biggest console makers, plus a `pc` bucket for desktop
 * platforms); every other slug — the retro/handheld/mobile/VR long tail —
 * returns `undefined`, which `ItemHero` renders with the same neutral
 * `bg-muted` style already used for the genre pills right above this row
 * (see that component), rather than inventing a fifth arbitrary color:
 * "no signal" reuses an existing, already-accessible style instead of one
 * made up for this feature.
 *
 * Distinct token namespace from FE-57's `--type-*` (`catalog-types.ts`,
 * `TYPE_COLOR_CLASSES`) on purpose (FE-60 acceptance) — same paired-token/
 * color-class-map *pattern*, but separate CSS variables (`--platform-*` in
 * `globals.css`) and separate hues, even though the two badges never appear
 * on the same page today: `--type-*` only renders on `CatalogCard`'s grids
 * (trending/browse/search/"similar"/home/library), never on the item detail
 * hero, while this only renders on the item detail hero. Keeping them
 * separate in code (rather than reusing `--type-game` for every platform,
 * say) means the two concepts — "what kind of item is this" vs. "which
 * console family made this platform" — stay independently themeable even
 * though nothing forces that separation visually yet.
 */
export type GamePlatform = components["schemas"]["GamePlatformOut"];

export type PlatformFamily = "playstation" | "xbox" | "nintendo" | "pc";

/**
 * Tailwind classes per family, same `bg-<token> text-<token>-foreground`
 * convention as `TYPE_COLOR_CLASSES` (`catalog-types.ts`) and
 * `STATUS_COLOR_CLASSES` (`library-types.ts`). No entry for "unrecognized" —
 * callers fall back to the neutral genre-pill style instead (see this
 * module's doc comment).
 */
export const PLATFORM_COLOR_CLASSES: Record<PlatformFamily, string> = {
  playstation: "bg-platform-playstation text-platform-playstation-foreground",
  xbox: "bg-platform-xbox text-platform-xbox-foreground",
  nintendo: "bg-platform-nintendo text-platform-nintendo-foreground",
  pc: "bg-platform-pc text-platform-pc-foreground",
};

/**
 * Slugs (pulled from the dev catalog's `game_platforms` table, 73 distinct
 * rows as of 2026-08-25) that belong to a family but don't contain the
 * family's name as a slug *prefix* — mostly pre-"branded" Nintendo
 * generations (`wii`, `gb`/`gba`/`gbc`, `sfam`, `famicom`) that predate
 * Nintendo putting its own name in the product name. Exact matches, not
 * prefixes: a slug is added here only when it's a real value seen in the
 * catalog, so a *similarly spelled but unrelated* future IGDB slug can't
 * false-positive into a family it doesn't belong to.
 */
const NINTENDO_EXACT_SLUGS = new Set(["sfam", "famicom"]);

/**
 * Slug prefixes covering full console generations at once (e.g. `ps`
 * matches `ps`/`ps2`/`ps3`/`ps4--1`/`ps5`/`psp`/`psvita`/`psvr` — every
 * PlayStation-family slug IGDB has assigned so far, and, by construction,
 * any future one too) — this is the actual "family/prefix grouping" the
 * acceptance criteria asks for, as opposed to enumerating all 60+ slugs.
 */
const NINTENDO_PREFIXES = [
  "switch",
  "wii",
  "gb",
  "3ds",
  "new-3ds",
  "n64",
  "nds",
  "nes",
  "ngc",
  "snes",
];

/**
 * `pc`/`win`/`mac`/`linux`/`dos` are exact matches, not a `pc`-prefix check
 * — IGDB's `pc-8800-series` (a 1980s Japanese NEC computer) starts with
 * "pc" but is not a modern desktop platform; a prefix match would have
 * mislabeled it. Falls through to the neutral retro bucket instead, which
 * is the correct outcome for it.
 */
const PC_EXACT_SLUGS = new Set(["win", "pc", "mac", "linux", "dos"]);

/**
 * Name substring for the `pc` family's fallback check, deliberately
 * "microsoft windows" rather than bare "windows" — the real slug (`win`)'s
 * name is "PC (Microsoft Windows)", but IGDB also has `winphone`/"Windows
 * Phone", a mobile platform that contains "windows" without being a desktop
 * one. Matching the fuller phrase catches the desktop platform while still
 * falling through to the neutral retro bucket for the phone.
 */
const PC_NAME_SUBSTRING = "microsoft windows";

/**
 * Classifies a single `GamePlatformOut` into a {@link PlatformFamily}, or
 * `undefined` when it doesn't recognizably belong to one (the retro/mobile/
 * VR/arcade long tail, or a malformed/empty slug — never throws). Checks
 * `slug` first (prefix/exact, cheap and stable — IGDB slugs don't change
 * once assigned) and falls back to a case-insensitive substring check on
 * `name` for the handful of real slugs that don't spell out their brand
 * (`series-x-s` for "Xbox Series X|S", `new-3ds` for "New Nintendo 3DS") —
 * so a brand-new IGDB platform the catalog has never seen still gets
 * classified correctly as long as its name mentions the brand, and safely
 * falls back to `undefined` (never a broken/uncolored badge) when it
 * doesn't.
 */
export function platformFamily(platform: GamePlatform): PlatformFamily | undefined {
  const slug = platform.slug?.trim().toLowerCase() ?? "";
  const name = platform.name?.trim().toLowerCase() ?? "";
  if (!slug && !name) {
    return undefined;
  }

  if (slug.startsWith("ps") || name.includes("playstation")) {
    return "playstation";
  }
  if (slug.startsWith("xbox") || name.includes("xbox")) {
    return "xbox";
  }
  if (
    NINTENDO_PREFIXES.some((prefix) => slug.startsWith(prefix)) ||
    NINTENDO_EXACT_SLUGS.has(slug) ||
    name.includes("nintendo")
  ) {
    return "nintendo";
  }
  if (PC_EXACT_SLUGS.has(slug) || name.includes(PC_NAME_SUBSTRING)) {
    return "pc";
  }
  return undefined;
}
