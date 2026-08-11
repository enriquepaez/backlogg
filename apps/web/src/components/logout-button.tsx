"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { useLogout } from "@/lib/auth/use-logout";

/**
 * Standalone logout action, backed by `useLogout` (shared with the account
 * dropdown menu item in `user-nav.tsx`). Not currently mounted by the header
 * — `UserNav` renders its own `DropdownMenuItem` for that — but kept as a
 * reusable, independently tested primitive for future surfaces that want a
 * plain logout button (e.g. FE-17 account settings).
 */
export function LogoutButton() {
  const t = useTranslations("Nav");
  const { logout, pending } = useLogout();

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={logout}
      disabled={pending}
    >
      {t("logout")}
    </Button>
  );
}
