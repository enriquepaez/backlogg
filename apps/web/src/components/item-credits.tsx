export type ItemCredit = {
  person_name: string;
  person_slug: string;
  profile_url: string | null;
  role: string;
  character_name: string | null;
  billing_order: number | null;
};

export type ItemCreditsProps = {
  /** Already ordered by `billing_order` ascending — see `docs/api.md`'s `CreditOut`. */
  credits: ItemCredit[];
  heading: string;
  emptyMessage: string;
  /**
   * Translated label per raw backend `role` (`creditRoleLabels` in
   * `@/lib/credit-role-labels`), pre-translated by the page like
   * `heading`/`emptyMessage`. Partial by design *in its keys*: any role
   * missing from the map renders raw.
   *
   * The prop itself is **required**, though. A caller that omits it doesn't
   * get "the previous behaviour", it gets exactly the defect this feature
   * exists to fix — schema identifiers (`SOURCE_AUTHOR`) printed at the user
   * — silently, with no type error and no failing test. Making it mandatory
   * turns that invariant into something the compiler enforces, which is
   * cheaper than a test (reviewer's O-4).
   */
  roleLabels: Record<string, string>;
};

/**
 * Credits list for the item detail page (FE-10 acceptance: "render de ...
 * credits"), shared by all four catalog types: cast & crew for movies/
 * series/games, author(s) (`role: "AUTHOR"`) for books.
 *
 * `character_name` is raw catalog content and is rendered as-is (same policy
 * as titles/genres). `role` is **not** catalog content but backend
 * vocabulary, so since FE-65 it goes through `roleLabels`: with backend
 * feature 74 live, an adapted movie/series now carries `SOURCE_AUTHOR` and
 * `WRITER` crew entries, and printing those raw put schema identifiers in
 * front of the user *and* hid the very distinction feature 74 exists to
 * create (author of the source work vs. screenwriter of the adaptation —
 * `docs/schema.md`, "`SOURCE_AUTHOR` vs `WRITER`"). Unknown roles still fall
 * back to the raw value, so new backend vocabulary degrades instead of
 * disappearing. The list stays flat — no per-role grouping or subheadings
 * (FE-65 asks for distinct labels, not grouping, and group headings would
 * reintroduce the orphan-heading risk its own acceptance criteria forbid).
 *
 * What this section covers is cast + screenplay + authorship of the source
 * work. Director/creator are **not** here: the page filters them out before
 * this component sees them (`getCredits` in `[type]/[slug]/page.tsx`), since
 * the hero's metadata `dl` already names them. This component stays
 * presentational and knows nothing about that layout decision — it renders
 * whatever list it is handed.
 *
 * No link to a person detail page:
 * `frontend_feature_list.json` has no such feature planned yet. Purely
 * presentational, like `CatalogCard`/`CatalogSection` (FE-8/FE-9) — `heading`/
 * `emptyMessage` come pre-translated from the page (a single type-agnostic
 * "Credits" label, not "Cast & crew" — see `[type]/[slug]/page.tsx`'s
 * `getCredits`).
 *
 * Defends against `credits` arriving `undefined`/falsy even though
 * `ItemCreditsProps` types it as always an array: `getCredits` already
 * normalizes this at the call site, but this component degrades to the
 * empty state itself too rather than trust every caller to do so — a
 * `credits: []` from the backend has been observed reaching here as
 * `undefined` for at least one real item (see `progress/history.md`).
 */
export function ItemCredits({
  credits,
  heading,
  emptyMessage,
  roleLabels,
}: ItemCreditsProps) {
  const items = credits ?? [];
  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{heading}</h2>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <ul className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 md:grid-cols-4">
          {items.map((credit, index) => {
            // Cast entries keep showing the character (FE-10 behaviour,
            // unchanged): the role label is what a credit *without* a
            // character gets, which since backend feature 89 is exactly the
            // crew — `character_name` always arrives `null` for it
            // (`docs/api.md`). `roleLabels` is a partial map, so an
            // unrecognized role falls through to the raw value.
            const secondaryLine =
              credit.character_name ?? roleLabels[credit.role] ?? credit.role;
            return (
              <li
                key={`${credit.person_slug}-${credit.role}-${index}`}
                className="min-w-0"
              >
                <p className="truncate text-sm font-medium" title={credit.person_name}>
                  {credit.person_name}
                </p>
                {/* `title` too: translated role labels ("Autoría de la obra
                    original") are longer than the raw codes were and can
                    truncate in a narrow grid column. */}
                <p className="truncate text-xs text-muted-foreground" title={secondaryLine}>
                  {secondaryLine}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
