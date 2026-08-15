"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
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
import { useRouter } from "@/i18n/navigation";

type SubmitState = "idle" | "submitting" | "error";
type ErrorKind = "unauthorized" | "forbidden" | "notFound" | "unknown";

export type DeleteListDialogProps = {
  slug: string;
  title: string;
};

/**
 * "Delete list" control (FE-25), one per `UserListCard` when `isOwner`.
 * Two-step confirmation like `report-review-button.tsx` (open the dialog,
 * then an explicit destructive submit) but no "type to confirm" gate like
 * `delete-account-dialog.tsx` — deleting one list is far less consequential
 * than deleting the whole account (no cross-domain cascade: ratings,
 * follows, library and other lists are untouched), so a plain confirm
 * button is enough friction.
 *
 * `DELETE /v1/lists/{slug}` cascades the list's own items server-side
 * (`docs/api.md`) — nothing extra to clean up client-side. On success,
 * `router.refresh()` re-fetches the profile page's lists grid so the card
 * disappears without a full reload, same mechanism `delete-account-dialog.tsx`
 * uses for its own post-delete navigation.
 */
export function DeleteListDialog({ slug, title }: DeleteListDialogProps) {
  const t = useTranslations("Profile.lists.delete");
  const router = useRouter();

  const [open, setOpen] = useState(false);
  const [state, setState] = useState<SubmitState>("idle");
  const [errorKind, setErrorKind] = useState<ErrorKind>("unknown");

  function resetDialogState() {
    setState("idle");
    setErrorKind("unknown");
  }

  async function handleConfirm() {
    setState("submitting");

    let response: Response;
    try {
      response = await fetch(`/api/lists/${slug}`, { method: "DELETE" });
    } catch {
      setErrorKind("unknown");
      setState("error");
      return;
    }

    if (response.status === 204) {
      setOpen(false);
      toast.success(t("success"));
      router.refresh();
      return;
    }

    setErrorKind(
      response.status === 401
        ? "unauthorized"
        : response.status === 403
          ? "forbidden"
          : response.status === 404
            ? "notFound"
            : "unknown",
    );
    setState("error");
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
          aria-label={t("openDialog", { title })}
        >
          <Trash2 aria-hidden />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("heading")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        {state === "error" ? (
          <p role="alert" className="text-sm text-destructive">
            {t(errorKind)}
          </p>
        ) : null}

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              {t("cancel")}
            </Button>
          </DialogClose>
          <Button
            type="button"
            variant="destructive"
            disabled={state === "submitting"}
            onClick={handleConfirm}
          >
            {state === "submitting" ? t("confirming") : t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
