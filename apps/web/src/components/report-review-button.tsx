"use client";

import { useState } from "react";
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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type SubmitState = "idle" | "submitting" | "error";

/**
 * Standalone "report this review" control (FE-18 acceptance: "Reportar
 * review ... con motivo; idempotente"). Only needs the numeric rating id
 * (`docs/api.md`: `POST /v1/reviews/{id}/report`, `{id}` = `user_ratings.id`)
 * — deliberately generic (not coupled to "the viewer's own rating") so
 * FE-19 (`reviews_display_likes`, the reviews listing) can mount this same
 * component next to any review once it ships. `rating-widget.tsx` is the
 * only mount point today, next to the viewer's own saved rating — FE-18's
 * scope has no other review surfaced on the item detail page yet
 * (`progress/current.md`).
 *
 * Two-step confirmation like `delete-account-dialog.tsx`: opening the
 * dialog, then an explicit submit — but no "type to confirm" gate, since
 * reporting isn't destructive to the reporter's own data. Reason is
 * optional (`ReportReasonIn.reason?`, `docs/api.md`), max 300 chars
 * (backend `Field(max_length=300)`, mirrored here as a UX guard via
 * `maxLength`).
 *
 * Idempotent per (reporter, review) on the backend: this component treats a
 * repeat report the same as a first one (no error), and locally disables the
 * trigger after any success so a caller can't spam duplicate reports in one
 * session — not required for correctness (the backend already dedupes), but
 * avoids a confusing "report again?" loop in the UI.
 */
export function ReportReviewButton({ ratingId }: { ratingId: number }) {
  const t = useTranslations("ItemDetail.report");

  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [state, setState] = useState<SubmitState>("idle");
  const [reported, setReported] = useState(false);

  function resetDialogState() {
    setReason("");
    setState("idle");
  }

  async function handleConfirm() {
    setState("submitting");

    let response: Response;
    try {
      response = await fetch(`/api/reviews/${ratingId}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason.trim() ? reason.trim() : null }),
      });
    } catch {
      setState("error");
      return;
    }

    if (response.status === 201 || response.status === 200) {
      setOpen(false);
      setReported(true);
      toast.success(t("success"));
      return;
    }

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
        <Button type="button" variant="ghost" size="sm" disabled={reported}>
          {reported ? t("reported") : t("openDialog")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("heading")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="report-review-reason">{t("reasonLabel")}</Label>
          <Textarea
            id="report-review-reason"
            maxLength={300}
            rows={3}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>

        {state === "error" ? (
          <p role="alert" className="text-sm text-destructive">
            {t("error")}
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
            {state === "submitting" ? t("submitting") : t("submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
