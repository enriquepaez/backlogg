import { getTranslations } from "next-intl/server";

import { getCurrentUser } from "@/lib/api-fetch";
import { Link } from "@/i18n/navigation";
import { GuestSettingsMenu } from "@/components/guest-settings-menu";
import { NavMenu } from "@/components/nav-menu";
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
 *
 * FE-55 "navbar decluttering" (direct user feedback: too many things
 * visible at once) cut this down to 4 nav destinations + the brand, from 8
 * separate links before: `Home` is gone (the brand link above already
 * points at `/`); `Showcase` is gone (an internal, untranslated kitchen-sink
 * page, not real product content — the route itself still exists, only the
 * public link was removed); `Trending`/`Genres` collapse into the
 * "Explore" `NavMenu`; `Feed`/`recommendations` collapse into the
 * "Activity" `NavMenu` (session-gated, same as before); `Search` and
 * `Library` stay as their own links — `Search` because it is the highest-
 * frequency action here (the visitor already knows what to type, so a
 * dropdown would add a needless extra click) and `Library` because it
 * didn't fit either dropdown's theme. `LanguageSwitcher`/`ModeToggle` are no
 * longer always-visible controls either — they moved inside `UserNav`'s
 * menu (session) or `GuestSettingsMenu` (no session), see those two doc
 * comments.
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
            <Link href="/search" className="hover:text-foreground">
              {t("search")}
            </Link>
            <NavMenu
              label={t("explore")}
              links={[
                { href: "/trending", label: t("trending") },
                { href: "/genres", label: t("genres") },
              ]}
            />
            {navUser ? (
              <>
                {/* `/feed` (FE-23) and `/recommendations` (FE-27) both
                    require a session — only surfaced once one exists, same
                    "auth-gated entry" idea as `UserNav`'s own entries
                    (profile/settings). Grouped under the "Activity" `NavMenu`
                    since FE-55: a signed-out viewer has nothing to see in
                    either (no following/ratings/library to base either on). */}
                <NavMenu
                  label={t("activity")}
                  links={[
                    { href: "/feed", label: t("feed") },
                    { href: "/recommendations", label: t("recommendations") },
                  ]}
                />
                {/* `/u/{username}/library` (FE-20/21) had no nav entry point
                    (FE-36) — same auth-gated shape as "Activity" above,
                    pointing at the signed-in user's own backlog. Kept as its
                    own link rather than folded into "Activity" (FE-55): it
                    doesn't share that dropdown's "what's happening" theme. */}
                <Link href={`/u/${navUser.username}/library`} className="hover:text-foreground">
                  {t("library")}
                </Link>
              </>
            ) : null}
          </nav>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {navUser ? (
            <>
              {/* Notifications (FE-24): auth-gated, same criterion as the
                  "Activity" nav dropdown above — a signed-out viewer has
                  nothing to be notified about. */}
              <NotificationBell />
              <UserNav user={navUser} />
            </>
          ) : (
            <>
              {/* FE-55: signed-out equivalent of the language/theme entries
                  `UserNav` gains once there is a session. */}
              <GuestSettingsMenu />
              {/* FE-13 builds the real /login page; the link already points
                  at its intended route (a 404 until then is expected and
                  self-explanatory during in-progress development). */}
              <Link href="/login" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
                {t("login")}
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
