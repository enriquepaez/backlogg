"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useRouter } from "@/i18n/navigation";
import { applyZodFieldErrors } from "@/lib/auth/schemas";
import { listSchema, type ListFormValues } from "@/lib/lists/schemas";

type SubmitError = "unauthorized" | "unknown" | null;

const DEFAULT_VALUES: ListFormValues = { title: "", description: "", isPublic: true };

/**
 * "Create a list" control for the profile page's lists section (FE-25),
 * mounted only when the viewer is looking at their own profile (see
 * `page.tsx`'s `isOwnProfile` gate, same as `DeleteAccountDialog`/
 * `AccountProfileForm` only ever rendering on `/settings`).
 *
 * Combines two patterns that previously lived in separate components:
 * `report-review-button.tsx`'s dialog scaffolding (open state, reset on
 * close) and `account-profile-form.tsx`'s react-hook-form + zod validation
 * with field/submit error split — this is the first form the app needs
 * inside a dialog.
 *
 * `POST /v1/lists` derives the slug from `title` server-side (`docs/api.md`)
 * — nothing to do with slugs here. On success the dialog closes and
 * `router.refresh()` re-fetches the Server Component page (`page.tsx`'s
 * `getUserLists` call), so the new list appears in the grid without a full
 * reload — same mechanism `account-profile-form.tsx` uses.
 */
export function CreateListDialog() {
  const t = useTranslations("Profile.lists.create");
  const tErrors = useTranslations("Profile.lists.create.errors");
  const router = useRouter();

  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<SubmitError>(null);

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ListFormValues>({ defaultValues: DEFAULT_VALUES });

  function resetDialogState() {
    reset(DEFAULT_VALUES);
    setSubmitError(null);
  }

  const fieldMessage = errors.title
    ? tErrors(errors.title.message ?? "title")
    : errors.description
      ? tErrors(errors.description.message ?? "description")
      : null;
  const submitMessage =
    fieldMessage ??
    (submitError === "unauthorized"
      ? t("unauthorized")
      : submitError === "unknown"
        ? t("unknown")
        : null);

  async function onSubmit(values: ListFormValues) {
    const parsed = listSchema.safeParse(values);
    if (!parsed.success) {
      applyZodFieldErrors(parsed.error, setError);
      return;
    }

    setSubmitError(null);

    let response: Response;
    try {
      response = await fetch("/api/lists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: parsed.data.title,
          description: parsed.data.description?.length ? parsed.data.description : null,
          is_public: parsed.data.isPublic,
        }),
      });
    } catch {
      setSubmitError("unknown");
      return;
    }

    if (response.status === 201) {
      setOpen(false);
      resetDialogState();
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
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          resetDialogState();
        }
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" size="sm">
          {t("openDialog")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{t("heading")}</DialogTitle>
            <DialogDescription>{t("description")}</DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="create-list-title">{t("titleLabel")}</Label>
            <Input id="create-list-title" aria-invalid={!!errors.title} {...register("title")} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="create-list-description">{t("descriptionLabel")}</Label>
            <Textarea
              id="create-list-description"
              rows={3}
              aria-invalid={!!errors.description}
              {...register("description")}
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              id="create-list-is-public"
              type="checkbox"
              className="size-4 rounded border-input"
              {...register("isPublic")}
            />
            <Label htmlFor="create-list-is-public">{t("isPublicLabel")}</Label>
          </div>

          <p
            role={submitMessage ? "alert" : undefined}
            className={`text-sm ${submitMessage ? "text-destructive" : "invisible"}`}
          >
            {submitMessage ?? " "}
          </p>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? t("submitting") : t("submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
