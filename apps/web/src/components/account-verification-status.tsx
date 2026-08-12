"use client";

import { CircleCheckIcon, MailWarningIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { useResendVerification } from "@/lib/auth/use-resend-verification";

/**
 * Email-verification status for the settings page (FE-17). Reuses
 * `useResendVerification` (FE-15's shared hook, also driving the "resend
 * verification" entry in `user-nav.tsx`'s account menu) rather than
 * reimplementing the request/toast logic — this component only owns its own
 * copy (a badge/CTA suited to a settled page section, distinct from a
 * dropdown menu item) and layout.
 */
export function AccountVerificationStatus({ emailVerified }: { emailVerified: boolean }) {
  const t = useTranslations("Settings.verification");
  const { resend, pending } = useResendVerification();

  if (emailVerified) {
    return (
      <p className="flex items-center gap-2 text-sm text-foreground">
        <CircleCheckIcon className="size-4 text-green-600" aria-hidden="true" />
        {t("verified")}
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <MailWarningIcon className="size-4 text-amber-600" aria-hidden="true" />
        {t("unverified")}
      </p>
      <Button type="button" variant="outline" size="sm" disabled={pending} onClick={resend}>
        {pending ? t("requesting") : t("verifyAction")}
      </Button>
    </div>
  );
}
