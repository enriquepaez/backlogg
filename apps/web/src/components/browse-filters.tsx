"use client";

import { useTranslations } from "next-intl";

import { useRouter } from "@/i18n/navigation";
import {
  CATALOG_SORTS,
  DEFAULT_CATALOG_SORT,
  type CatalogGenre,
  type CatalogSort,
  type CatalogType,
} from "@/lib/catalog-types";

export type BrowseFiltersProps = {
  type: CatalogType;
  genres: CatalogGenre[];
  selectedGenre?: string;
  selectedSort: CatalogSort;
};

// Unlike `<input>` (see `ui/input.tsx`), a native `<select>` doesn't reliably
// inherit `color`/`background-color` from the body across browsers — the
// popup listing its `<option>`s is rendered using the OS/browser's own
// `color-scheme` heuristics when the element doesn't declare one itself. If
// that heuristic disagrees with the site's `.dark` class (e.g. light OS theme
// + site dark mode), the browser can paint the widget with light-on-light or
// dark-on-dark text. `text-foreground` plus `bg-background` pins both layers
// to the site's actual theme colors, and `[color-scheme:light]
// dark:[color-scheme:dark]` tells the browser which native palette to use for
// chrome it still controls (e.g. the dropdown's scrollbar).
const SELECT_CLASSNAME =
  "h-8 min-w-0 rounded-lg border border-input bg-background px-2.5 py-1 text-base text-foreground transition-colors outline-none [color-scheme:light] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:[color-scheme:dark] dark:bg-input/30";

// Some browsers (notably Safari) don't reliably inherit `color`/
// `background-color` from the parent `<select>` into its `<option>` popup,
// so each option pins its own colors too.
const OPTION_CLASSNAME = "bg-background text-foreground";

/**
 * Genre + sort filter controls for `/browse/{type}` (FE-9). A client
 * component because changing either select navigates immediately (no
 * "Apply" button) — but the navigation itself always goes through
 * `router.replace` with a plain `{ pathname, query }` href, so the resulting
 * URL is the same shareable one a server-rendered link would produce (see
 * the page itself, which reads these same `genre`/`sort` query params from
 * `searchParams`). Changing a filter always resets `page` back to 1 — the
 * previous page number is very likely to be out of range for the new
 * filtered/sorted result set.
 */
export function BrowseFilters({
  type,
  genres,
  selectedGenre,
  selectedSort,
}: BrowseFiltersProps) {
  const router = useRouter();
  const t = useTranslations("Browse.filters");

  // Both fields are always passed explicitly (never merged from `next`
  // partially over `selectedGenre`/`selectedSort`) — an earlier version used
  // `next.genre ?? selectedGenre`, which made "clear the genre" (an
  // intentional `undefined`) indistinguishable from "genre wasn't touched by
  // this call" (also `undefined`), so clearing silently kept the old value.
  function navigate({ genre, sort }: { genre?: string; sort: CatalogSort }) {
    const query: Record<string, string> = {};
    if (genre) {
      query.genre = genre;
    }
    if (sort !== DEFAULT_CATALOG_SORT) {
      query.sort = sort;
    }
    router.replace({ pathname: `/browse/${type}`, query });
  }

  return (
    <div className="flex flex-wrap items-end gap-4">
      {/*
        Explicit `htmlFor`/`id` pairing (sibling label + select) rather than
        a wrapping `<label>`, so each label's accessible name is just its
        own text — not contaminated by the select's own rendered `<option>`
        text, which a wrapping label would fold in per the accname spec.
      */}
      <div className="flex flex-col gap-1">
        <label htmlFor="browse-genre" className="text-sm font-medium">
          {t("genreLabel")}
        </label>
        <select
          id="browse-genre"
          className={SELECT_CLASSNAME}
          value={selectedGenre ?? ""}
          onChange={(event) =>
            navigate({ genre: event.target.value || undefined, sort: selectedSort })
          }
        >
          <option value="" className={OPTION_CLASSNAME}>
            {t("genreAll")}
          </option>
          {genres.map((genre) => (
            <option key={genre.slug} value={genre.slug} className={OPTION_CLASSNAME}>
              {genre.name} ({genre.count})
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="browse-sort" className="text-sm font-medium">
          {t("sortLabel")}
        </label>
        <select
          id="browse-sort"
          className={SELECT_CLASSNAME}
          value={selectedSort}
          onChange={(event) =>
            navigate({ genre: selectedGenre, sort: event.target.value as CatalogSort })
          }
        >
          {CATALOG_SORTS.map((sort) => (
            <option key={sort} value={sort} className={OPTION_CLASSNAME}>
              {t(`sort.${sort}`)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
