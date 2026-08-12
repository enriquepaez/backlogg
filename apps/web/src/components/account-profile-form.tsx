"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useRouter } from "@/i18n/navigation";
import { applyZodFieldErrors } from "@/lib/auth/schemas";
import { profileSchema, type ProfileFormValues } from "@/lib/settings/schemas";

export type ProfileInitialValues = {
  displayName: string | null;
  bio: string | null;
  avatarUrl: string | null;
};

type SubmitError = "unauthorized" | "unknown" | null;

/**
 * Profile-edit form (FE-17): `display_name`, `bio`, `avatar_url` against
 * `PATCH /v1/users/me` (via `/api/users/me`, the FE-17 BFF proxy).
 *
 * Unlike `register-form.tsx`/`login-form.tsx`, this form does not navigate
 * away on success — it's the whole point of the settings page, the user
 * stays on it and keeps editing. So success is a toast (same pattern as
 * `use-resend-verification.ts`) rather than swapping the form out for a
 * static message, and the form is `reset()` to the values the backend
 * actually saved (clearing RHF's dirty state) rather than left as-is.
 * `router.refresh()` re-renders `site-header.tsx` (a Server Component) so
 * the nav's name/avatar picks up the change without a full reload — same
 * mechanism `use-logout.ts` uses.
 *
 * All three fields are sent together on every submit (not a per-field
 * diff): `UserUpdate` treats a present-but-`null` field as "clear it", so an
 * emptied input must round-trip as `null`, not be omitted — omitting it
 * would leave the previous value untouched instead of clearing it.
 */
export function AccountProfileForm({ initial }: { initial: ProfileInitialValues }) {
  const t = useTranslations("Settings.profile");
  const tErrors = useTranslations("Settings.profile.errors");
  const tGeneric = useTranslations("Settings");
  const router = useRouter();

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ProfileFormValues>({
    defaultValues: {
      displayName: initial.displayName ?? "",
      bio: initial.bio ?? "",
      avatarUrl: initial.avatarUrl ?? "",
    },
  });

  const [submitError, setSubmitError] = useState<SubmitError>(null);

  const fieldMessage = errors.displayName
    ? tErrors(errors.displayName.message ?? "displayName")
    : errors.bio
      ? tErrors(errors.bio.message ?? "bio")
      : errors.avatarUrl
        ? tErrors(errors.avatarUrl.message ?? "avatarUrl")
        : null;
  const submitMessage =
    fieldMessage ??
    (submitError === "unauthorized"
      ? t("unauthorized")
      : submitError === "unknown"
        ? tGeneric("genericError")
        : null);

  async function onSubmit(values: ProfileFormValues) {
    const parsed = profileSchema.safeParse(values);
    if (!parsed.success) {
      applyZodFieldErrors(parsed.error, setError);
      return;
    }

    setSubmitError(null);

    const displayName = parsed.data.displayName?.length ? parsed.data.displayName : null;
    const bio = parsed.data.bio?.length ? parsed.data.bio : null;
    const avatarUrl = parsed.data.avatarUrl?.length ? parsed.data.avatarUrl : null;

    let response: Response;
    try {
      response = await fetch("/api/users/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: displayName,
          bio,
          avatar_url: avatarUrl,
        }),
      });
    } catch {
      setSubmitError("unknown");
      return;
    }

    if (response.status === 200) {
      reset({
        displayName: displayName ?? "",
        bio: bio ?? "",
        avatarUrl: avatarUrl ?? "",
      });
      toast.success(t("success"));
      router.refresh();
      return;
    }

    if (response.status === 401) {
      setSubmitError("unauthorized");
      return;
    }

    // 422 (defensive — the client already validated) and anything else
    // surface as the same generic error.
    setSubmitError("unknown");
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="profile-display-name">{t("displayNameLabel")}</Label>
        <Input
          id="profile-display-name"
          autoComplete="name"
          aria-invalid={!!errors.displayName}
          {...register("displayName")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="profile-bio">{t("bioLabel")}</Label>
        <Textarea
          id="profile-bio"
          rows={3}
          aria-invalid={!!errors.bio}
          {...register("bio")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="profile-avatar-url">{t("avatarUrlLabel")}</Label>
        <Input
          id="profile-avatar-url"
          type="text"
          inputMode="url"
          autoComplete="photo"
          aria-invalid={!!errors.avatarUrl}
          {...register("avatarUrl")}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <p
          role={submitMessage ? "alert" : undefined}
          className={`text-sm ${submitMessage ? "text-destructive" : "invisible"}`}
        >
          {submitMessage ?? " "}
        </p>
        <Button type="submit" disabled={isSubmitting} className="self-start">
          {isSubmitting ? t("submitting") : t("submit")}
        </Button>
      </div>
    </form>
  );
}
