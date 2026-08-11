import { getTranslations } from "next-intl/server";

import { getCurrentUser } from "@/lib/api-fetch";
import { Link } from "@/i18n/navigation";
import { LanguageSwitcher } from "@/components/language-switcher";
import { ModeToggle } from "@/components/mode-toggle";
import { UserNav, type NavUser } from "@/components/user-nav";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * App-wide header: brand, primary nav, and the session-aware auth section.
 *
 * A Server Component so it can call `getCurrentUser()` directly (see
 * `src/lib/auth/proxy-refresh.ts` for why that is safe to do in render).
 * Renders on every page via `[locale]/layout.tsx`.
 */
export async function SiteHeader() {
  const t = await getTranslations("Nav");
  const user = await getCurrentUser();

  const navUser: NavUser | null = user
    ? {
        username: user.username,
        displayName: user.display_name,
        avatarUrl: user.avatar_url,
      }
    : null;

  return (
    <header className="border-b border-border bg-background">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-4 px-6 py-4 sm:px-10">
        <div className="flex flex-wrap items-center gap-6">
          <Link href="/" className="text-lg font-semibold tracking-tight">
            {t("brand")}
          </Link>
          <nav aria-label={t("primaryNav")} className="flex items-center gap-4 text-sm text-muted-foreground">
            <Link href="/" className="hover:text-foreground">
              {t("home")}
            </Link>
            <Link href="/search" className="hover:text-foreground">
              {t("search")}
            </Link>
            <Link href="/showcase" className="hover:text-foreground">
              {t("showcase")}
            </Link>
          </nav>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <LanguageSwitcher />
          <ModeToggle />
          {navUser ? (
            <UserNav user={navUser} />
          ) : (
            // FE-13 builds the real /login page; the link already points at
            // its intended route (a 404 until then is expected and
            // self-explanatory during in-progress development).
            <Link href="/login" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
              {t("login")}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
