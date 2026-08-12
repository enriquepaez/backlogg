"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { CircleCheckIcon, OctagonXIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Link } from "@/i18n/navigation";
import {
  applyZodFieldErrors,
  resetPasswordSchema,
  type ResetPasswordFormValues,
} from "@/lib/auth/schemas";
import { cn } from "@/lib/utils";

type ResetState = "form" | "success" | "invalid" | "error";

/**
 * Drives `/reset-password`'s single job: let the visitor pick a new password
 * and consume the `token` query param against `POST /api/auth/password/reset`
 * (the FE-16 BFF proxy, public — no session required).
 *
 * Unlike `verify-email-status.tsx` (which fires its confirmation call
 * automatically on mount, since a bare link click IS the whole action), reset
 * needs input from the user first — the token alone isn't enough, the new
 * password is part of the request body — so this renders a form instead of
 * an effect-driven spinner. The token itself is read server-side by the page
 * (`reset-password/page.tsx`'s `searchParams` prop) and passed down as a
 * plain prop, so this never needs `useSearchParams` (and therefore no
 * `Suspense` boundary), same reasoning as `verify-email-status.tsx`.
 *
 * A missing token short-circuits before any form is rendered — the request
 * body would fail the backend's own validation (`token` is required)
 * regardless of the password, so there's nothing useful for the user to type.
 *
 * On success the backend has already revoked every refresh token for the
 * account (`docs/api.md`) — this does not attempt to log the user in
 * automatically (there's no new session to have here, only a CTA back to
 * `/login`).
 */
export function ResetPasswordStatus({ token }: { token: string | undefined }) {
  const t = useTranslations("Auth.resetPassword");
  const tErrors = useTranslations("Auth.resetPassword.errors");
  const [state, setState] = useState<ResetState>(token ? "form" : "invalid");

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ResetPasswordFormValues>({ defaultValues: { password: "" } });

  const fieldMessage = errors.password ? tErrors(errors.password.message ?? "password") : null;
  const submitMessage = fieldMessage ?? (state === "error" ? t("error") : null);

  async function onSubmit(values: ResetPasswordFormValues) {
    if (!token) {
      return;
    }

    const parsed = resetPasswordSchema.safeParse(values);
    if (!parsed.success) {
      applyZodFieldErrors(parsed.error, setError);
      return;
    }

    let response: Response;
    try {
      response = await fetch("/api/auth/password/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: parsed.data.password }),
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
  }

  if (state === "invalid") {
    return <ErrorMessage message={token ? t("invalidToken") : t("missingToken")} />;
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

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="reset-password-password">{t("passwordLabel")}</Label>
        <Input
          id="reset-password-password"
          type="password"
          autoComplete="new-password"
          aria-invalid={!!errors.password}
          {...register("password")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <p
          role={submitMessage ? "alert" : undefined}
          className={`text-sm ${submitMessage ? "text-destructive" : "invisible"}`}
        >
          {submitMessage ?? " "}
        </p>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? t("submitting") : t("submit")}
        </Button>
      </div>
    </form>
  );
}

function ErrorMessage({ message }: { message: string }) {
  const t = useTranslations("Auth.resetPassword");

  return (
    <div className="flex flex-col gap-4">
      <p role="alert" className="flex items-center gap-2 text-sm text-destructive">
        <OctagonXIcon className="size-4" aria-hidden="true" />
        {message}
      </p>
      <Link
        href="/forgot-password"
        className={cn(buttonVariants({ variant: "outline", size: "sm" }), "self-start")}
      >
        {t("backToForgot")}
      </Link>
    </div>
  );
}
