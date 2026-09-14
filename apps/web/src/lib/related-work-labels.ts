/**
 * The two directions a related work can sit on, keyed by the raw backend
 * value of `AdaptationOut.direction` (`docs/api.md`, backend feature 92).
 * Read from the point of view of the item whose page you are on:
 *
 * - `SOURCE` — the item on the page *is based on* the related one ("this
 *   film comes from this novel").
 * - `DERIVED` — the related item *comes out of* the item on the page ("this
 *   novel got adapted into this series").
 *
 * Declared here as the UI's own vocabulary (same shape as
 * `credit-role-labels.ts`'s `CREDIT_ROLE_CODES` and `game-type-labels.ts`'s
 * `GAME_TYPE_CODES`: the codes and their copy live together) rather than
 * re-deriving `components["schemas"]["AdaptationDirection"]` in every
 * consumer. `@/lib/catalog`'s `RelatedWork.direction` uses *this* type while
 * assigning the generated schema's value into it, so a third direction added
 * backend-side becomes a type error at that assignment instead of a label
 * silently resolving to `undefined` in the rendered page.
 *
 * Zero imports on purpose — like `catalog-types.ts`, this module must be
 * reachable from Server Components, Client Components and plain Vitest
 * suites alike, with no transitive `server-only`.
 */
export const RELATED_WORK_DIRECTIONS = ["SOURCE", "DERIVED"] as const;

export type RelatedWorkDirection = (typeof RELATED_WORK_DIRECTIONS)[number];

/**
 * The minimal translator shape this module needs — same contract (and same
 * reasoning) as `game-type-labels.ts`'s / `credit-role-labels.ts`'s
 * `Translate`, plus the interpolation values next-intl's `t(key, values)`
 * takes, since both messages here name the item the user is looking at.
 */
type Translate = (key: string, values?: Record<string, string>) => string;

/**
 * Translated sentence per direction, for `ItemRelatedWorks`'
 * `directionLabels` prop. Built in the page — which owns both the
 * `ItemDetail` translator and the title being interpolated — so the
 * component stays purely presentational, exactly like its `heading` and
 * like `ItemCredits`' `roleLabels`.
 *
 * Both messages interpolate `itemTitle` (the title of the item *on the
 * page*, never the related one) on purpose: the section is a single neutral
 * list ("Obras relacionadas" / "Related works", per the user's decision on
 * FE-66), so each entry has to say which way the relation runs on its own
 * rather than relying on its position in the list or on two separate
 * headings. Naming the anchor item is what makes "Obra derivada de Better
 * Call Saul" unambiguous under a card titled *Slippin' Jimmy*.
 *
 * Exhaustive `Record`, not the partial map `creditRoleLabels` returns: this
 * vocabulary is a closed two-value enum in the backend schema, not an
 * open-ended list the backend may extend with new roles, so there is no
 * unknown-value case to fall back from — and the type checker keeps both
 * branches covered.
 */
export function relatedWorkDirectionLabels(
  t: Translate,
  itemTitle: string,
): Record<RelatedWorkDirection, string> {
  return {
    SOURCE: t("relatedWorks.directions.SOURCE", { title: itemTitle }),
    DERIVED: t("relatedWorks.directions.DERIVED", { title: itemTitle }),
  };
}
