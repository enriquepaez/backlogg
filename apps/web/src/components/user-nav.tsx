"use client";

import { LogOut } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useLogout } from "@/lib/auth/use-logout";

/**
 * Minimal, client-safe subset of `UserMeOut` — deliberately excludes `email`
 * and `email_verified`. Passing the full DTO from the Server Component down
 * to this (client-rendered) component would ship those fields to the
 * browser for no reason (see `node_modules/next/dist/docs/01-app/02-guides/data-security.md`,
 * "Component-level data access": pass only what the UI needs).
 */
export type NavUser = {
  username: string;
  displayName: string | null;
  avatarUrl: string | null;
};

function initials(user: NavUser): string {
  const source = user.displayName ?? user.username;
  return source.slice(0, 2).toUpperCase();
}

/**
 * Session-aware header entry point (FE-14: "menú de cuenta con logout").
 *
 * A Radix `DropdownMenu` (shadcn/ui primitives, `src/components/ui/dropdown-
 * menu.tsx`) rather than the previous inline avatar+name+button: it is the
 * natural place to hang the account entries later features add (edit
 * profile / verify email / delete account in FE-17, notifications in FE-24,
 * etc.) without another header restructure, and it comes with
 * click-outside/Escape-to-close and full keyboard navigation for free from
 * Radix. Today it only has one item (logout), but the trigger already reads
 * as an account affordance rather than a bare logout button.
 */
export function UserNav({ user }: { user: NavUser }) {
  const t = useTranslations("Nav");
  const { logout, pending } = useLogout();
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
            // Avatar hosts aren't configured in `next/image`'s remotePatterns
            // yet (catalog-image scope, later features); a plain <img> avoids
            // that dependency for now.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={user.avatarUrl}
              alt=""
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
        <DropdownMenuItem variant="destructive" disabled={pending} onSelect={logout}>
          <LogOut aria-hidden="true" />
          {t("logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
