"use client";

import { useTransition } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useRouter } from "@/i18n/navigation";

/**
 * Shared client-side logout action, extracted from `logout-button.tsx` so
 * `user-nav.tsx`'s account dropdown menu item and the standalone
 * `LogoutButton` (reusable elsewhere, e.g. a future FE-17 account-settings
 * "danger zone") drive the exact same behavior instead of two divergent
 * copies of it.
 */
export function useLogout() {
  const t = useTranslations("Nav");
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function logout() {
    startTransition(async () => {
      try {
        // Route Handler, not a direct backend call: it is the only place
        // (besides a Server Action) allowed to clear the httpOnly auth
        // cookies — see `src/app/api/auth/logout/route.ts`.
        const res = await fetch("/api/auth/logout", { method: "POST" });
        if (!res.ok) {
          throw new Error(`logout failed with status ${res.status}`);
        }
        // Re-render the current route's Server Components (the nav
        // included) against the now-cleared cookies, without a full page
        // reload.
        router.refresh();
      } catch (error) {
        // The Route Handler already clears cookies best-effort even when
        // the backend revoke call fails, so this only fires for a genuine
        // network/client-side failure to reach our own BFF — surface it
        // rather than silently leaving the nav in a stale "logged in"
        // state. This is the app shell's toast pattern in its one real,
        // load-bearing use (see `src/components/ui/sonner.tsx`, mounted in
        // `[locale]/layout.tsx`).
        console.error(error);
        toast.error(t("logoutError"));
      }
    });
  }

  return { logout, pending };
}
