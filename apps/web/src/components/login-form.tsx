"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Link, useRouter } from "@/i18n/navigation";
import { applyZodFieldErrors, loginSchema, type LoginFormValues } from "@/lib/auth/schemas";
import { useCountdown } from "@/lib/use-countdown";

type SubmitError = "invalid_credentials" | "rate_limited" | "unknown" | null;

/**
 * Login form (FE-13). Client component: `react-hook-form` owns field state
 * and validates against `loginSchema` (zod) before ever hitting the network.
 * Submits to `/api/auth/login` (the existing BFF Route Handler from FE-4/FE-5,
 * unchanged by this feature) — never the backend directly, so the browser
 * never sees the token pair, only the httpOnly cookies that route sets.
 *
 * Validation only happens on submit (`loginSchema.safeParse` in `onSubmit`
 * below, via `applyZodFieldErrors`) — nothing is checked while typing or on
 * blur. Invalid credentials (401) are likewise only detected on submit.
 */
export function LoginForm() {
  const t = useTranslations("Auth.login");
  const tErrors = useTranslations("Auth.login.errors");
  const tRateLimited = useTranslations("Auth.rateLimited");
  const tGeneric = useTranslations("Auth");
  const router = useRouter();

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    defaultValues: { username: "", password: "" },
  });

  const [submitError, setSubmitError] = useState<SubmitError>(null);
  const [retryAfterSeconds, setRetryAfterSeconds] = useState<number | null>(null);
  const remaining = useCountdown(retryAfterSeconds);
  const rateLimited = retryAfterSeconds !== null && remaining > 0;

  // Single message + tone for the reserved slot above the submit button —
  // this is the ONLY place any error (per-field format error or
  // submit-level 401/429/unknown) is shown; nothing renders under the
  // inputs themselves. Field errors take priority (they're what's blocking
  // the user right now) and are checked in field order; submit-level
  // errors only show once every field is valid.
  const fieldMessage = errors.username
    ? tErrors(errors.username.message ?? "username")
    : errors.password
      ? tErrors(errors.password.message ?? "password")
      : null;
  const submitMessage =
    fieldMessage ??
    (submitError === "invalid_credentials"
      ? t("invalidCredentials")
      : submitError === "unknown"
        ? tGeneric("genericError")
        : rateLimited
          ? tRateLimited("waiting", { seconds: remaining })
          : submitError === "rate_limited"
            ? tRateLimited("ready")
            : null);
  const submitMessageTone =
    fieldMessage || submitError === "invalid_credentials" || submitError === "unknown"
      ? "text-destructive"
      : "text-muted-foreground";

  async function onSubmit(values: LoginFormValues) {
    const parsed = loginSchema.safeParse(values);
    if (!parsed.success) {
      applyZodFieldErrors(parsed.error, setError);
      return;
    }

    setSubmitError(null);

    let response: Response;
    try {
      response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed.data),
      });
    } catch {
      setSubmitError("unknown");
      return;
    }

    if (response.ok) {
      // Re-render Server Components (the nav included) against the new
      // session cookies, same as `logout-button.tsx`'s `router.refresh()`.
      router.push("/");
      router.refresh();
      return;
    }

    if (response.status === 429) {
      setRetryAfterSeconds(parseRetryAfter(response));
      setSubmitError("rate_limited");
      return;
    }

    if (response.status === 401) {
      setSubmitError("invalid_credentials");
      return;
    }

    setSubmitError("unknown");
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="login-username">{t("usernameLabel")}</Label>
        <Input
          id="login-username"
          autoComplete="username"
          aria-invalid={!!errors.username}
          {...register("username")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor="login-password">{t("passwordLabel")}</Label>
          <Link
            href="/forgot-password"
            className="text-sm text-muted-foreground underline-offset-4 hover:underline"
          >
            {t("forgotPasswordLink")}
          </Link>
        </div>
        <Input
          id="login-password"
          type="password"
          autoComplete="current-password"
          aria-invalid={!!errors.password}
          {...register("password")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <p
          role={submitMessage ? "alert" : undefined}
          className={`text-sm ${submitMessage ? submitMessageTone : "invisible"}`}
        >
          {submitMessage ?? " "}
        </p>
        <Button type="submit" disabled={isSubmitting || rateLimited}>
          {isSubmitting ? t("submitting") : t("submit")}
        </Button>
      </div>
    </form>
  );
}

function parseRetryAfter(response: Response): number {
  const header = response.headers.get("Retry-After");
  if (!header) {
    return 0;
  }
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : 0;
}
