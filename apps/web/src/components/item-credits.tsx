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
};

/**
 * Credits list for the item detail page (FE-10 acceptance: "render de ...
 * credits"), shared by all four catalog types: cast & crew for movies/
 * series/games, author(s) (`role: "AUTHOR"`) for books. `role`/
 * `character_name` are raw backend vocabulary (not enumerated in
 * `docs/api.md`) — rendered as-is rather than mapped through i18n, same
 * policy as other catalog content (see `apps/web/AGENTS.md` / i18n note
 * referenced from `CatalogCard`). No link to a person detail page:
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
export function ItemCredits({ credits, heading, emptyMessage }: ItemCreditsProps) {
  const items = credits ?? [];
  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{heading}</h2>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <ul className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 md:grid-cols-4">
          {items.map((credit, index) => (
            <li
              key={`${credit.person_slug}-${credit.role}-${index}`}
              className="min-w-0"
            >
              <p className="truncate text-sm font-medium" title={credit.person_name}>
                {credit.person_name}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {credit.character_name ?? credit.role}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
