import { getTranslations } from "next-intl/server";

import { getCurrentUser } from "@/lib/api-fetch";
import { Link } from "@/i18n/navigation";
import { LanguageSwitcher } from "@/components/language-switcher";
import { ModeToggle } from "@/components/mode-toggle";
import { NotificationBell } from "@/components/notification-bell";
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
        emailVerified: user.email_verified,
      }
    : null;

  return (
    <header className="border-b border-border bg-background">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-4 sm:px-8 xl:flex-row xl:items-center xl:justify-between">
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
            <Link href="/trending" className="hover:text-foreground">
              {t("trending")}
            </Link>
            <Link href="/genres" className="hover:text-foreground">
              {t("genres")}
            </Link>
            <Link href="/showcase" className="hover:text-foreground">
              {t("showcase")}
            </Link>
            {navUser ? (
              <>
                {/* `/feed` (FE-23) requires a session — only surfaced in the
                    primary nav once one exists, same "auth-gated entry" idea as
                    `UserNav`'s own entries (profile/settings), just placed here
                    instead since it is a full nav destination, not an account
                    action. */}
                <Link href="/feed" className="hover:text-foreground">
                  {t("feed")}
                </Link>
                {/* `/recommendations` (FE-27) is the same shape of auth-gated
                    nav destination as `/feed` right above it — a signed-out
                    viewer has no ratings/library to base recommendations on. */}
                <Link href="/recommendations" className="hover:text-foreground">
                  {t("recommendations")}
                </Link>
                {/* `/u/{username}/library` (FE-20/21) had no nav entry point
                    (FE-36) — same auth-gated shape as `/feed` and
                    `/recommendations` above, pointing at the signed-in
                    user's own backlog. */}
                <Link href={`/u/${navUser.username}/library`} className="hover:text-foreground">
                  {t("library")}
                </Link>
              </>
            ) : null}
          </nav>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <LanguageSwitcher />
          <ModeToggle />
          {navUser ? (
            <>
              {/* Notifications (FE-24): auth-gated, same criterion as the
                  `/feed` nav link above — a signed-out viewer has nothing to
                  be notified about. */}
              <NotificationBell />
              <UserNav user={navUser} />
            </>
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
