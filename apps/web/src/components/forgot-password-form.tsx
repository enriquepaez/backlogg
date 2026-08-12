"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  applyZodFieldErrors,
  forgotPasswordSchema,
  type ForgotPasswordFormValues,
} from "@/lib/auth/schemas";

type SubmitState = "idle" | "success" | "error";

/**
 * Forgot-password form (FE-16). Client component: `react-hook-form` owns
 * field state and validates the email format against `forgotPasswordSchema`
 * (zod) before ever hitting the network — purely to skip a pointless round
 * trip for an obviously malformed input, same as `login-form.tsx`.
 *
 * Submits to `/api/auth/password/forgot` (the BFF proxy for
 * `POST /v1/auth/password/forgot`, `docs/api.md`), which answers `202`
 * unconditionally whether or not the email is registered. This form mirrors
 * that neutrality end to end: `success` renders ONE static message
 * regardless of what the backend actually did, and is reached for both a
 * `202` AND a backend `422` (a malformed-but-schema-passing address, e.g.
 * one the client's own regex missed) — the user never learns anything about
 * whether the address exists. Only a genuine network failure (`catch`) or an
 * unexpected non-`202`/`422` status falls back to a generic error, which
 * itself says nothing about the email either.
 */
export function ForgotPasswordForm() {
  const t = useTranslations("Auth.forgotPassword");
  const tErrors = useTranslations("Auth.forgotPassword.errors");
  const tGeneric = useTranslations("Auth");

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ForgotPasswordFormValues>({ defaultValues: { email: "" } });

  const [state, setState] = useState<SubmitState>("idle");

  const fieldMessage = errors.email ? tErrors(errors.email.message ?? "email") : null;
  const submitMessage =
    fieldMessage ?? (state === "error" ? tGeneric("genericError") : null);

  async function onSubmit(values: ForgotPasswordFormValues) {
    const parsed = forgotPasswordSchema.safeParse(values);
    if (!parsed.success) {
      applyZodFieldErrors(parsed.error, setError);
      return;
    }

    let response: Response;
    try {
      response = await fetch("/api/auth/password/forgot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed.data),
      });
    } catch {
      setState("error");
      return;
    }

    if (response.status === 202 || response.status === 422) {
      setState("success");
      return;
    }

    setState("error");
  }

  if (state === "success") {
    return (
      <p role="status" className="text-sm text-foreground">
        {t("success")}
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="forgot-password-email">{t("emailLabel")}</Label>
        <Input
          id="forgot-password-email"
          type="email"
          autoComplete="email"
          aria-invalid={!!errors.email}
          {...register("email")}
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
