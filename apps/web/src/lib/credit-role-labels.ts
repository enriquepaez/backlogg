/**
 * The roles the item detail page already shows in the hero's metadata `dl`,
 * and therefore the ones the "Credits" section must **not** repeat:
 * `DIRECTOR` (movie) and `CREATOR` (series) are rendered by `buildFields`
 * via `peopleByRole` in the fixed "who's responsible" slot (position 2 —
 * `docs/detail-page-layout.md`). Per the user's explicit decision
 * ("los credits no deben incluir dirección, el director va en el hero" ·
 * "Director en el hero y actores en credits"), listing them again a few
 * hundred pixels below is duplication, so `getCredits` filters them out.
 *
 * Exported as its own named constant — rather than hardcoding two strings
 * inside `getCredits` — so the "this comes out of the hero, that's why it's
 * not in Credits" relationship is written in the code and not only in a
 * comment: this list and {@link CREDIT_ROLE_CODES} are the two halves of the
 * same vocabulary split.
 *
 * `AUTHOR` (book) is *also* in the hero `dl`, but it isn't here: book never
 * renders the Credits section at all (`getCredits`' caller), so filtering it
 * would be dead code, and `AUTHOR` remains part of the renderable vocabulary
 * for the day the section is extended.
 */
export const HERO_ROLES = ["DIRECTOR", "CREATOR"] as const;

/**
 * Person-credit roles the "Credits" section can actually render, keyed by
 * `CreditOut.role` (`docs/api.md`'s `credits[]`, `docs/schema.md`'s
 * "People & Credits" → "Supported roles by domain"): the cast entries merged
 * in from `item_cast` (always `ACTOR`), the two adaptation roles this feature
 * is about (`WRITER`/`SOURCE_AUTHOR`, backend feature 74) and `AUTHOR`
 * (books). Games have no person credits at all.
 *
 * `DIRECTOR`/`CREATOR` are deliberately **absent**: they belong to
 * {@link HERO_ROLES} and never reach this section, so carrying copy for them
 * here would be dead vocabulary. Keeping the two lists disjoint is what lets
 * the copy-parity test ("a code with no copy fails") stay meaningful.
 */
export const CREDIT_ROLE_CODES = ["ACTOR", "WRITER", "AUTHOR", "SOURCE_AUTHOR"] as const;

export type CreditRoleCode = (typeof CREDIT_ROLE_CODES)[number];

/**
 * The minimal translator shape this module needs — same contract (and same
 * reasoning) as `game-type-labels.ts`'s `Translate`: matches next-intl's
 * `useTranslations`/`getTranslations` return value called with a single
 * dynamic key, and a plain test double, without importing next-intl's
 * namespace-scoped translator type here.
 */
type Translate = (key: string) => string;

/**
 * Translated label per known credit role, keyed by the raw backend value, for
 * `ItemCredits`' `roleLabels` prop. Built in the page (which owns the
 * `ItemDetail` translator) so the component itself stays purely
 * presentational, exactly like its `heading`/`emptyMessage`.
 *
 * Deliberately a *partial* map over the raw `role` string rather than an
 * exhaustive `Record<string, string>`: a role the backend adds later simply
 * isn't in it, and `ItemCredits` falls back to rendering the raw value — the
 * same never-break-on-unknown-vocabulary policy the component had before
 * this map existed (and the same spirit as `gameTypeLabel`'s `other`
 * fallback, minus the generic bucket, since "Other" says strictly less than
 * the raw role does here).
 */
export function creditRoleLabels(t: Translate): Record<string, string> {
  return Object.fromEntries(
    CREDIT_ROLE_CODES.map((code) => [code, t(`credits.roles.${code}`)]),
  );
}
