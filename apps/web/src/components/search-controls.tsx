"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Input } from "@/components/ui/input";
import { useRouter } from "@/i18n/navigation";
import { CATALOG_TYPES, type CatalogType } from "@/lib/catalog-types";

export type SearchControlsProps = {
  /** Current `q` from the URL — the single source of truth this component debounces edits against. */
  initialQuery: string;
  initialType?: CatalogType;
};

/**
 * Wait this long after the user stops typing before pushing `q` to the URL.
 * No precedent elsewhere in the repo (FE-9's filters navigate immediately on
 * `onChange` since a `<select>` change is already a deliberate, discrete
 * action) — a free-text input firing one navigation (and one `/v1/search`
 * request) per keystroke would be wasteful and, worse, would burn through
 * the backend's per-IP external-fallback rate limit on the very sequence of
 * queries transitioning to the user's final, complete word.
 */
const DEBOUNCE_MS = 400;

const SELECT_CLASSNAME =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2.5 py-1 text-base text-foreground transition-colors outline-none [color-scheme:light] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:[color-scheme:dark] dark:bg-input/30";
const OPTION_CLASSNAME = "bg-background text-foreground";

/**
 * Search input (debounced) + type filter for `/search` (FE-11). A client
 * component because typing needs local, instantaneous input state — but,
 * like `BrowseFilters` (FE-9), the actual state lives in the URL: every
 * committed change goes through `router.replace({ pathname, query })`, so
 * `/search?q=...&type=...` stays shareable and the page's Server Component
 * re-fetches on every change.
 *
 * The debounce effect compares the trimmed local value against
 * `initialQuery` (the URL's current `q`, i.e. what the last fetch actually
 * used) instead of tracking "did the user touch this" with a ref: on mount,
 * and whenever the URL changes for a reason OTHER than this component's own
 * `q` edit (e.g. the type filter, pagination links, or the browser back
 * button), the two are equal and the effect is a no-op — only a genuine,
 * still-pending local edit ever schedules a navigation.
 */
export function SearchControls({ initialQuery, initialType }: SearchControlsProps) {
  const router = useRouter();
  const t = useTranslations("Search");
  const [value, setValue] = useState(initialQuery);

  // The URL is the source of truth: if it changes underneath us (filter
  // change, pagination, back/forward, or a shared link), sync the visible
  // input to match rather than let it drift. Adjusted during render (React's
  // documented "store the previous prop and compare" pattern) instead of in
  // an effect, so this doesn't fire a redundant extra render on every prop
  // change (see https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes).
  const [syncedQuery, setSyncedQuery] = useState(initialQuery);
  if (initialQuery !== syncedQuery) {
    setSyncedQuery(initialQuery);
    setValue(initialQuery);
  }

  useEffect(() => {
    const trimmed = value.trim();
    if (trimmed === initialQuery) {
      return;
    }
    const handle = setTimeout(() => {
      navigate({ q: trimmed, type: initialType });
    }, DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // Only re-run when the pending value itself changes — `initialType` and
    // `initialQuery` are read fresh inside the closure but must not, by
    // themselves, restart the debounce window while the user is still typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  function navigate({ q, type }: { q: string; type?: CatalogType }) {
    const query: Record<string, string> = {};
    if (q) {
      query.q = q;
    }
    if (type) {
      query.type = type;
    }
    router.replace({ pathname: "/search", query });
  }

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="flex min-w-48 flex-1 flex-col gap-1">
        <label htmlFor="search-q" className="text-sm font-medium">
          {t("inputLabel")}
        </label>
        <Input
          id="search-q"
          type="search"
          placeholder={t("placeholder")}
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="search-type" className="text-sm font-medium">
          {t("filters.typeLabel")}
        </label>
        <select
          id="search-type"
          className={SELECT_CLASSNAME}
          value={initialType ?? ""}
          onChange={(event) =>
            navigate({
              q: value.trim(),
              type: (event.target.value || undefined) as CatalogType | undefined,
            })
          }
        >
          <option value="" className={OPTION_CLASSNAME}>
            {t("filters.all")}
          </option>
          {CATALOG_TYPES.map((type) => (
            <option key={type} value={type} className={OPTION_CLASSNAME}>
              {t(`filters.${type}`)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
