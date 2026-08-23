"use client";

import { CircleUserRound, Library, LogOut, MailCheck, Settings } from "lucide-react";
import { useTranslations } from "next-intl";
import Image from "next/image";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Link } from "@/i18n/navigation";
import { useLogout } from "@/lib/auth/use-logout";
import { useResendVerification } from "@/lib/auth/use-resend-verification";

/**
 * Minimal, client-safe subset of `UserMeOut` — deliberately excludes `email`.
 * Passing the full DTO from the Server Component down to this (client-
 * rendered) component would ship that field to the browser for no reason
 * (see `node_modules/next/dist/docs/01-app/02-guides/data-security.md`,
 * "Component-level data access": pass only what the UI needs). `emailVerified`
 * IS included (FE-15): it drives whether the "resend verification" menu item
 * below renders, which is a UI decision, not sensitive data.
 */
export type NavUser = {
  username: string;
  displayName: string | null;
  avatarUrl: string | null;
  emailVerified: boolean;
};

function initials(user: NavUser): string {
  const source = user.displayName ?? user.username;
  return source.slice(0, 2).toUpperCase();
}

/**
 * Session-aware header entry point (FE-14: "menú de cuenta con logout";
 * FE-15 adds the conditional "resend verification" entry; FE-17 adds the
 * "settings" entry linking to `/settings`, the only entry point into that
 * page's profile-edit/delete-account flows; a post-QA follow-up on FE-21
 * adds the "my profile" entry linking to `/u/{username}`, the public
 * profile page that previously had no header entry point; FE-36 adds the
 * "library" entry linking to `/u/{username}/library`, which also had no
 * nav entry point).
 *
 * A Radix `DropdownMenu` (shadcn/ui primitives, `src/components/ui/dropdown-
 * menu.tsx`) rather than the previous inline avatar+name+button: it is the
 * natural place to hang the account entries later features add (notifications
 * in FE-24, etc.) without another header restructure, and it comes with
 * click-outside/Escape-to-close and full keyboard navigation for free from
 * Radix.
 */
export function UserNav({ user }: { user: NavUser }) {
  const t = useTranslations("Nav");
  const { logout, pending: loggingOut } = useLogout();
  const { resend, pending: resending } = useResendVerification();
  const name = user.displayName ?? user.username;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="gap-2"
          aria-label={t("accountMenu")}
        >
          {user.avatarUrl ? (
            <Image
              src={user.avatarUrl}
              alt=""
              width={24}
              height={24}
              className="size-6 rounded-full object-cover"
            />
          ) : (
            <span
              aria-hidden="true"
              className="flex size-6 items-center justify-center rounded-full bg-muted text-xs"
            >
              {initials(user)}
            </span>
          )}
          <span className="max-w-32 truncate">{name}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel className="max-w-48 truncate">{name}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href={`/u/${user.username}`}>
            <CircleUserRound aria-hidden="true" />
            {t("profile")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={`/u/${user.username}/library`}>
            <Library aria-hidden="true" />
            {t("library")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/settings">
            <Settings aria-hidden="true" />
            {t("settings")}
          </Link>
        </DropdownMenuItem>
        {!user.emailVerified ? (
          <>
            <DropdownMenuItem disabled={resending} onSelect={resend}>
              <MailCheck aria-hidden="true" />
              {t("resendVerification")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        ) : null}
        <DropdownMenuItem variant="destructive" disabled={loggingOut} onSelect={logout}>
          <LogOut aria-hidden="true" />
          {t("logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
