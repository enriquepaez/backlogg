"use client";

import { useTranslations } from "next-intl";

import { useRouter } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import {
  DEFAULT_LIBRARY_SORT,
  LIBRARY_SORTS,
  type LibrarySort,
  type LibraryStatusValue,
} from "@/lib/library-types";

export type LibrarySortSelectProps = {
  username: string;
  status?: LibraryStatusValue;
  type?: CatalogType;
  selectedSort: LibrarySort;
};

// Same cross-browser native-<select> theming rationale as `BrowseFilters`
// (`src/components/browse-filters.tsx`, FE-9) — see that file's doc comment
// for why plain `<select>`/`<option>` need explicit `text-foreground`/
// `bg-background`/`color-scheme` instead of relying on inheritance.
const SELECT_CLASSNAME =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2.5 py-1 text-base text-foreground transition-colors outline-none [color-scheme:light] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:[color-scheme:dark] dark:bg-input/30";

const OPTION_CLASSNAME = "bg-background text-foreground";

/**
 * Sort control for `/u/{username}/library` (FE-38) — same `?sort=`
 * convention as `BrowseFilters` (FE-9): a client component that navigates
 * via `router.replace` on change (no "Apply" button), so the resulting URL
 * is the same shareable/reloadable one a server-rendered link would
 * produce (`page.tsx` reads this same `sort` query param from
 * `searchParams`, same as `BrowseFilters`' page reads `genre`/`sort`).
 *
 * Unlike `BrowseFilters`, this renders only one select — `status`/`type` on
 * this page are driven by `StatusTabs`/`TypeTabs` (plain server-rendered
 * `Link`s in `page.tsx`), not by this component. `status`/`type` are still
 * accepted as props so a sort change preserves whichever ones are
 * currently active, and changing sort always resets `page` back to 1 (the
 * previous page number is very likely out of range once the entries are
 * reordered), same rationale as `BrowseFilters.navigate`.
 */
export function LibrarySortSelect({ username, status, type, selectedSort }: LibrarySortSelectProps) {
  const router = useRouter();
  const t = useTranslations("Library.sort");

  function navigate(sort: LibrarySort) {
    const query: Record<string, string> = {};
    if (status) {
      query.status = status;
    }
    if (type) {
      query.type = type;
    }
    if (sort !== DEFAULT_LIBRARY_SORT) {
      query.sort = sort;
    }
    router.replace({ pathname: `/u/${username}/library`, query });
  }

  return (
    <div className="flex flex-col gap-1">
      {/*
        Explicit `htmlFor`/`id` pairing (sibling label + select) rather than
        a wrapping `<label>` — same reasoning as `BrowseFilters`.
      */}
      <label htmlFor="library-sort" className="text-sm font-medium">
        {t("label")}
      </label>
      <select
        id="library-sort"
        className={SELECT_CLASSNAME}
        value={selectedSort}
        onChange={(event) => navigate(event.target.value as LibrarySort)}
      >
        {LIBRARY_SORTS.map((sort) => (
          <option key={sort} value={sort} className={OPTION_CLASSNAME}>
            {t(sort)}
          </option>
        ))}
      </select>
    </div>
  );
}
