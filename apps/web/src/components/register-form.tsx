"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRouter } from "@/i18n/navigation";
import { applyZodFieldErrors, registerSchema, type RegisterFormValues } from "@/lib/auth/schemas";
import { useCountdown } from "@/lib/use-countdown";

type SubmitError = "conflict" | "rate_limited" | "unknown" | null;

/**
 * Registration form (FE-13). Client component: `react-hook-form` owns field
 * state and validates against `registerSchema` (zod, a mirror of the
 * backend's `UserCreate`) before ever hitting the network.
 *
 * Validation only happens on submit (`registerSchema.safeParse` in
 * `onSubmit` below, via `applyZodFieldErrors`) — nothing is checked while
 * typing or on blur. Duplicate username/email (409) is likewise only
 * detected on submit.
 *
 * `POST /v1/auth/register` (proxied by `/api/auth/register`) returns the
 * created profile (`UserMeOut`), NOT a token pair — registering alone can't
 * create a session. Rather than dropping the user on a bare "account
 * created, now log in" screen right after they just typed a username and
 * password, a successful 201 here immediately chains a second call to the
 * existing `/api/auth/login` Route Handler with those same credentials, so
 * they land signed in. If that second call fails for any reason (e.g. the
 * rate limit trips between the two requests), the account still exists, so
 * this falls back to sending them to `/login` instead of retrying silently
 * or showing a dead form — a toast (`Auth.login.accountCreated`) makes that
 * explicit so the user doesn't read the redirect as the signup having
 * failed.
 */
export function RegisterForm() {
  const t = useTranslations("Auth.register");
  const tErrors = useTranslations("Auth.register.errors");
  const tRateLimited = useTranslations("Auth.rateLimited");
  const tGeneric = useTranslations("Auth");
  const tLogin = useTranslations("Auth.login");
  const router = useRouter();

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    defaultValues: { username: "", email: "", password: "", displayName: "" },
  });

  const [submitError, setSubmitError] = useState<SubmitError>(null);
  const [retryAfterSeconds, setRetryAfterSeconds] = useState<number | null>(null);
  const remaining = useCountdown(retryAfterSeconds);
  const rateLimited = retryAfterSeconds !== null && remaining > 0;

  // Single message + tone for the reserved slot above the submit button —
  // this is the ONLY place any error (per-field format error or
  // submit-level 409/429/unknown) is shown; nothing renders under the
  // inputs themselves. Field errors take priority (they're what's blocking
  // the user right now) and are checked in field order; submit-level
  // errors only show once every field is valid.
  const fieldMessage = errors.username
    ? tErrors(errors.username.message ?? "username")
    : errors.email
      ? tErrors(errors.email.message ?? "email")
      : errors.password
        ? tErrors(errors.password.message ?? "password")
        : errors.displayName
          ? tErrors(errors.displayName.message ?? "displayName")
          : null;
  const submitMessage =
    fieldMessage ??
    (submitError === "conflict"
      ? t("conflict")
      : submitError === "unknown"
        ? tGeneric("genericError")
        : rateLimited
          ? tRateLimited("waiting", { seconds: remaining })
          : submitError === "rate_limited"
            ? tRateLimited("ready")
            : null);
  const submitMessageTone =
    fieldMessage || submitError === "conflict" || submitError === "unknown"
      ? "text-destructive"
      : "text-muted-foreground";

  async function onSubmit(values: RegisterFormValues) {
    const parsed = registerSchema.safeParse(values);
    if (!parsed.success) {
      applyZodFieldErrors(parsed.error, setError);
      return;
    }

    setSubmitError(null);

    const displayName = parsed.data.displayName && parsed.data.displayName.length > 0
      ? parsed.data.displayName
      : null;

    let registerResponse: Response;
    try {
      registerResponse = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: parsed.data.username,
          email: parsed.data.email,
          password: parsed.data.password,
          display_name: displayName,
        }),
      });
    } catch {
      setSubmitError("unknown");
      return;
    }

    if (registerResponse.status === 201) {
      try {
        const loginResponse = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: parsed.data.username, password: parsed.data.password }),
        });
        if (loginResponse.ok) {
          router.push("/");
          router.refresh();
          return;
        }
      } catch {
        // fall through to the /login redirect below — the account was
        // still created successfully.
      }
      // The chained login above failed (bad response or a thrown network
      // error), but the outer 201 means the account itself was created.
      // Surface that via a toast before sending the user to /login so they
      // don't think the whole signup failed — same "real but recoverable,
      // don't block the flow" pattern as `logout-button.tsx`.
      toast.success(tLogin("accountCreated"));
      router.push("/login");
      return;
    }

    if (registerResponse.status === 409) {
      setSubmitError("conflict");
      return;
    }

    if (registerResponse.status === 429) {
      setRetryAfterSeconds(parseRetryAfter(registerResponse));
      setSubmitError("rate_limited");
      return;
    }

    // 422 (defensive — the client already validated) and anything else
    // surface as the same generic error; the form's own field-level
    // messages already cover the specific validation cases.
    setSubmitError("unknown");
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="register-username">{t("usernameLabel")}</Label>
        <Input
          id="register-username"
          autoComplete="username"
          aria-invalid={!!errors.username}
          {...register("username")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="register-email">{t("emailLabel")}</Label>
        <Input
          id="register-email"
          type="email"
          autoComplete="email"
          aria-invalid={!!errors.email}
          {...register("email")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="register-password">{t("passwordLabel")}</Label>
        <Input
          id="register-password"
          type="password"
          autoComplete="new-password"
          aria-invalid={!!errors.password}
          {...register("password")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="register-display-name">
          {t("displayNameLabel")}{" "}
          <span className="text-muted-foreground">{t("displayNameOptional")}</span>
        </Label>
        <Input
          id="register-display-name"
          autoComplete="name"
          aria-invalid={!!errors.displayName}
          {...register("displayName")}
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
