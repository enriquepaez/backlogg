"use client";

import { useTranslations } from "next-intl";

import { Link, usePathname } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

const SECTIONS = ["overview", "users", "movies", "series", "books", "games"] as const;
type Section = (typeof SECTIONS)[number];

const HREF_BY_SECTION: Record<Section, string> = {
  overview: "/admin",
  users: "/admin/users",
  movies: "/admin/movies",
  series: "/admin/series",
  books: "/admin/books",
  games: "/admin/games",
};

/**
 * `pathname` (from `@/i18n/navigation`'s `usePathname`, locale-stripped) is
 * an exact route for every section here except `overview`, whose own href
 * (`/admin`) is a PREFIX of every other section's href — `startsWith` alone
 * would keep "Overview" highlighted on every admin page. `overview` matches
 * only exactly; every other section also matches its own detail routes
 * (e.g. `/admin/users/alice` still highlights "Users").
 */
function isActive(pathname: string, section: Section): boolean {
  const href = HREF_BY_SECTION[section];
  if (section === "overview") return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Persistent nav for the whole `/admin/*` surface (FE-33): Overview, Users
 * (functional), Movies/Series/Books/Games (stubs — FE-34 fills these in).
 * Rendered once by `@/app/[locale]/admin/layout.tsx`, beside `{children}`,
 * so every admin route shares the same shell instead of each page (or the
 * old single `/admin` page) re-implementing navigation.
 *
 * A plain `Link` list rather than shadcn's `sidebar` primitive — that one
 * ships a provider/cookie-persisted collapse state this app has no other use
 * for yet (`progress/current.md`'s FE-33 plan), and there's no existing
 * drawer/hamburger pattern in this app to match on mobile either, so this
 * just wraps onto a horizontal row above the content at small widths
 * (`flex-row` by default, `md:flex-col` once there's room for a real
 * sidebar column).
 *
 * A Client Component (needs `usePathname` to highlight the active section)
 * — cheap enough that it doesn't need to be a Server Component, same
 * tradeoff every other small interactive nav bit in this app makes (e.g.
 * `LanguageSwitcher`).
 */
export function AdminSidebar() {
  const t = useTranslations("Admin.sidebar");
  const pathname = usePathname();

  return (
    <nav aria-label={t("nav")} className="flex shrink-0 flex-row flex-wrap gap-2 md:w-48 md:flex-col">
      {SECTIONS.map((section) => {
        const active = isActive(pathname, section);
        return (
          <Link
            key={section}
            href={HREF_BY_SECTION[section]}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t(section)}
          </Link>
        );
      })}
    </nav>
  );
}
