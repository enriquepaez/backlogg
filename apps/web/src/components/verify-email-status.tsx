"use client";

import { useEffect, useRef, useState } from "react";
import { CircleCheckIcon, Loader2, OctagonXIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

type VerifyState = "missing" | "loading" | "success" | "invalid" | "error";

/**
 * Drives `/verify-email`'s single job: consume the `token` query param
 * against `POST /api/auth/verify/confirm` (the FE-15 BFF proxy, public — no
 * session required) and render the outcome. A client component because it
 * needs an effect to fire the (non-idempotent) confirmation call exactly
 * once on mount; the token itself is read server-side by the page
 * (`verify-email/page.tsx`'s `searchParams` prop) and passed down as a plain
 * prop, so this never needs `useSearchParams` (and therefore no `Suspense`
 * boundary — see `node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-search-params.md`,
 * "If you're already in a Server Component Page, consider using the
 * `searchParams` prop").
 */
export function VerifyEmailStatus({ token }: { token: string | undefined }) {
  const t = useTranslations("Auth.verifyEmail");
  const [state, setState] = useState<VerifyState>(token ? "loading" : "missing");
  // Guards against firing the confirmation call twice for the same token —
  // React 19's Strict Mode double-invokes effects in dev, and this call
  // consumes a single-use token: a second POST would (correctly, but
  // confusingly) come back as "already used" instead of "verified".
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) {
      return;
    }
    attempted.current = true;

    (async () => {
      let response: Response;
      try {
        response = await fetch("/api/auth/verify/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
      } catch {
        setState("error");
        return;
      }

      if (response.ok) {
        setState("success");
      } else if (response.status === 400) {
        setState("invalid");
      } else {
        setState("error");
      }
    })();
  }, [token]);

  if (state === "missing") {
    return <ErrorMessage message={t("missingToken")} />;
  }

  if (state === "loading") {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        {t("verifying")}
      </p>
    );
  }

  if (state === "success") {
    return (
      <div className="flex flex-col gap-4">
        <p role="status" className="flex items-center gap-2 text-sm text-foreground">
          <CircleCheckIcon className="size-4 text-green-600" aria-hidden="true" />
          {t("success")}
        </p>
        <Link
          href="/login"
          className={cn(buttonVariants({ variant: "default", size: "sm" }), "self-start")}
        >
          {t("continueCta")}
        </Link>
      </div>
    );
  }

  return <ErrorMessage message={state === "invalid" ? t("invalidToken") : t("error")} />;
}

function ErrorMessage({ message }: { message: string }) {
  const t = useTranslations("Auth.verifyEmail");

  return (
    <div className="flex flex-col gap-4">
      <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
        <OctagonXIcon className="size-4" aria-hidden="true" />
        {message}
      </p>
      <Link
        href="/"
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "self-start")}
      >
        {t("backHome")}
      </Link>
    </div>
  );
}
