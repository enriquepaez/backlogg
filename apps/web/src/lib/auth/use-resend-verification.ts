"use client";

import { useTransition } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

/**
 * Shared client-side "resend verification email" action (FE-15), mirroring
 * `use-logout.ts`'s shape so `user-nav.tsx`'s account dropdown menu item
 * drives the exact same request/toast pattern as logout does. Only mounted
 * where a session is known to exist (the account menu already gates the
 * whole surface on `getCurrentUser()` — see `site-header.tsx`), so a 401 here
 * would mean the session died between render and click, which is reported
 * the same as any other failure rather than given special handling.
 */
export function useResendVerification() {
  const t = useTranslations("Nav");
  const [pending, startTransition] = useTransition();

  function resend() {
    startTransition(async () => {
      try {
        // Route Handler, not a direct backend call: it is the one that
        // attaches the session's access token server-side — see
        // `src/app/api/auth/verify/request/route.ts`.
        const res = await fetch("/api/auth/verify/request", { method: "POST" });
        if (!res.ok) {
          throw new Error(`resend verification failed with status ${res.status}`);
        }
        toast.success(t("resendVerificationSuccess"));
      } catch (error) {
        console.error(error);
        toast.error(t("resendVerificationError"));
      }
    });
  }

  return { resend, pending };
}
