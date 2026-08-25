/**
 * IGDB game-category codes surfaced as `GameOut.game_type` (`docs/api.md`) —
 * mirrors `GAME_TYPE_MAP` in `backlogg/games/constants.py` (indices 0-14,
 * 15 entries total). Only 8 of these are ingestable today
 * (`ALLOWED_GAME_TYPES`, backend feature `game_category_allowlist`:
 * `MAIN_GAME`/`DLC_ADDON`/`EXPANSION`/`STANDALONE_EXPANSION`/`EPISODE`/
 * `SEASON`/`REMAKE`/`REMASTER`), but this list covers all 15 so that a game
 * already in a user's library, ingested before that allowlist existed and
 * tagged with one of the 7 now-excluded categories (`BUNDLE`/`MOD`/
 * `EXPANDED_GAME`/`PORT`/`FORK`/`PACK`/`UPDATE`), still gets a translated
 * label on its item detail page instead of regressing to the raw enum name.
 */
export const GAME_TYPE_CODES = [
  "MAIN_GAME",
  "DLC_ADDON",
  "EXPANSION",
  "BUNDLE",
  "STANDALONE_EXPANSION",
  "MOD",
  "EPISODE",
  "SEASON",
  "REMAKE",
  "REMASTER",
  "EXPANDED_GAME",
  "PORT",
  "FORK",
  "PACK",
  "UPDATE",
] as const;

export type GameTypeCode = (typeof GAME_TYPE_CODES)[number];

function isGameTypeCode(value: string): value is GameTypeCode {
  return (GAME_TYPE_CODES as readonly string[]).includes(value);
}

/**
 * The minimal translator shape this module needs — matches both next-intl's
 * `useTranslations`/`getTranslations` return value (called with a single
 * string key, no interpolation values, same as `ItemDetailPage`'s existing
 * `tBadge(\`typeBadge.${type}\`)` dynamic-key usage) and a plain test double,
 * without importing next-intl's namespace-scoped translator type here.
 */
type Translate = (key: string) => string;

/**
 * Translates a raw `game_type` value into a human label via
 * `ItemDetail.gameTypes.<CODE>` (`messages/{en,es}.json`), falling back to
 * `ItemDetail.gameTypes.other` ("Other"/"Otro") for any value outside the
 * known {@link GAME_TYPE_CODES} — covers a future IGDB category this map
 * hasn't been updated for yet, so the item detail page degrades to a
 * generic label instead of crashing or showing the untranslated raw enum
 * name. Callers are responsible for the "value is absent" case (`GameOut.
 * game_type` is typed as a required string, but defensive callers may still
 * see `null`/`undefined` at runtime, e.g. `ItemDetailPage`'s `buildFields`,
 * which uses its own "Not available" placeholder for that instead of
 * routing it through this fallback).
 */
export function gameTypeLabel(value: string, t: Translate): string {
  return t(`gameTypes.${isGameTypeCode(value) ? value : "other"}`);
}
