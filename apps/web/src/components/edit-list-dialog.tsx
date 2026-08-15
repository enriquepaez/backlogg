"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
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

import type { components } from "@backlogg/api-client";

type UserListSummary = components["schemas"]["UserListSummary"];

export type EditListDialogProps = {
  list: UserListSummary;
};

type SubmitError = "unauthorized" | "forbidden" | "notFound" | "unknown" | null;

function toFormValues(list: UserListSummary): ListFormValues {
  return {
    title: list.title,
    description: list.description ?? "",
    isPublic: list.is_public,
  };
}

/**
 * "Edit list" control (FE-25), one per `UserListCard` when `isOwner`. Same
 * dialog + react-hook-form/zod combo as `create-list-dialog.tsx`, pre-filled
 * from the current list instead of blank defaults, and targeting
 * `PATCH /api/lists/{slug}` instead of `POST /api/lists`.
 *
 * No dedicated list-detail page exists yet to host this control (that's
 * FE-26's `GET /v1/lists/{slug}` page, `frontend_feature_list.json`) —
 * editing/deleting both happen inline from the profile's lists grid, the
 * only place a list is rendered today.
 *
 * On success the form is `reset()` to the values the backend actually saved
 * (clearing RHF's dirty state), same as `account-profile-form.tsx`, and
 * `router.refresh()` re-fetches the Server Component page so the card's own
 * summary text picks up the change without a full reload.
 */
export function EditListDialog({ list }: EditListDialogProps) {
  const t = useTranslations("Profile.lists.edit");
  const tErrors = useTranslations("Profile.lists.edit.errors");
  const router = useRouter();

  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<SubmitError>(null);

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ListFormValues>({ defaultValues: toFormValues(list) });

  function resetDialogState() {
    reset(toFormValues(list));
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
      : submitError === "forbidden"
        ? t("forbidden")
        : submitError === "notFound"
          ? t("notFound")
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

    const description = parsed.data.description?.length ? parsed.data.description : null;

    let response: Response;
    try {
      response = await fetch(`/api/lists/${list.slug}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: parsed.data.title,
          description,
          is_public: parsed.data.isPublic,
        }),
      });
    } catch {
      setSubmitError("unknown");
      return;
    }

    if (response.status === 200) {
      setOpen(false);
      reset({ title: parsed.data.title, description: description ?? "", isPublic: parsed.data.isPublic });
      toast.success(t("success"));
      router.refresh();
      return;
    }

    if (response.status === 401) {
      setSubmitError("unauthorized");
      return;
    }
    if (response.status === 403) {
      setSubmitError("forbidden");
      return;
    }
    if (response.status === 404) {
      setSubmitError("notFound");
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
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("openDialog", { title: list.title })}
        >
          <Pencil aria-hidden />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{t("heading")}</DialogTitle>
          </DialogHeader>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`edit-list-title-${list.slug}`}>{t("titleLabel")}</Label>
            <Input
              id={`edit-list-title-${list.slug}`}
              aria-invalid={!!errors.title}
              {...register("title")}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`edit-list-description-${list.slug}`}>{t("descriptionLabel")}</Label>
            <Textarea
              id={`edit-list-description-${list.slug}`}
              rows={3}
              aria-invalid={!!errors.description}
              {...register("description")}
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              id={`edit-list-is-public-${list.slug}`}
              type="checkbox"
              className="size-4 rounded border-input"
              {...register("isPublic")}
            />
            <Label htmlFor={`edit-list-is-public-${list.slug}`}>{t("isPublicLabel")}</Label>
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
