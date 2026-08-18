"use client";

import { useEffect } from "react";
import { Columns3, LayoutGrid } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { useRouter } from "@/i18n/navigation";
import type { CatalogType } from "@/lib/catalog-types";
import {
  DEFAULT_LIBRARY_SORT,
  DEFAULT_LIBRARY_VIEW,
  type LibrarySort,
  type LibraryStatusValue,
  type LibraryView,
} from "@/lib/library-types";

export type LibraryViewToggleProps = {
  username: string;
  status?: LibraryStatusValue;
  type?: CatalogType;
  sort: LibrarySort;
  /** The view `page.tsx` resolved server-side (`?view=` if present, `"grid"` otherwise). */
  view: LibraryView;
  /** Whether `?view=` was actually present in the URL, vs. defaulted — see this component's doc comment. */
  hasExplicitView: boolean;
};

/** `localStorage` key for one user's grid/board preference — per-username so it never leaks across accounts sharing a browser (FE-43). */
function storageKeyFor(username: string): string {
  return `backlogg:library-view:${username}`;
}

/**
 * Grid/board toggle for `/u/{username}/library` (FE-43) — only ever rendered
 * by `page.tsx` for the viewer's own library (`isOwnLibrary`), never on
 * someone else's, which always stays the read-only grid with no toggle at
 * all.
 *
 * Same `?view=` URL-driven convention as `LibrarySortSelect`'s `?sort=`
 * (`router.replace` with a plain `{ pathname, query }` href, so the result is
 * shareable/reloadable and `page.tsx` can read it straight off
 * `searchParams`, no client-only state) — but this control additionally
 * persists the choice to `localStorage`, per-username
 * ({@link storageKeyFor}), so it's remembered on a plain revisit that carries
 * no `?view=` at all. That persistence is a one-shot redirect-on-mount: if
 * `hasExplicitView` is `false` (the URL had no `?view=`) and a saved
 * preference exists and disagrees with the resolved `view`, this replaces
 * the URL with the saved one. The effect only runs once per mount
 * (`hasExplicitView`/`view` read at mount time, not tracked reactively) since
 * every subsequent view change already goes through `navigate`, which keeps
 * the URL and `localStorage` in sync itself.
 */
export function LibraryViewToggle({
  username,
  status,
  type,
  sort,
  view,
  hasExplicitView,
}: LibraryViewToggleProps) {
  const router = useRouter();
  const t = useTranslations("Library.view");

  function navigate(nextView: LibraryView) {
    window.localStorage.setItem(storageKeyFor(username), nextView);
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
    if (nextView !== DEFAULT_LIBRARY_VIEW) {
      query.view = nextView;
    }
    router.replace({ pathname: `/u/${username}/library`, query });
  }

  useEffect(() => {
    if (hasExplicitView) {
      return;
    }
    const saved = window.localStorage.getItem(storageKeyFor(username));
    if ((saved === "grid" || saved === "board") && saved !== view) {
      navigate(saved);
    }
    // One-shot redirect on mount only — see doc comment above for why
    // `hasExplicitView`/`view`/`username`/`navigate` are intentionally read
    // fresh instead of re-running this effect when any of them change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div role="group" aria-label={t("label")} className="inline-flex items-center gap-1 rounded-lg border border-border p-1">
      <Button
        type="button"
        size="sm"
        variant={view === "grid" ? "secondary" : "ghost"}
        aria-pressed={view === "grid"}
        onClick={() => navigate("grid")}
      >
        <LayoutGrid />
        {t("grid")}
      </Button>
      <Button
        type="button"
        size="sm"
        variant={view === "board" ? "secondary" : "ghost"}
        aria-pressed={view === "board"}
        onClick={() => navigate("board")}
      >
        <Columns3 />
        {t("board")}
      </Button>
    </div>
  );
}
