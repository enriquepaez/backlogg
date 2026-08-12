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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRouter } from "@/i18n/navigation";

type SubmitState = "idle" | "submitting" | "error";

/**
 * Account-deletion control (FE-17). Two independent confirmations are
 * required before `DELETE /v1/users/me` ever fires: opening the dialog
 * itself (a deliberate second click, not the destructive action) and typing
 * the account's own `username` into a text input that must match exactly
 * before the destructive button enables — the same "type to confirm"
 * pattern used by most account-deletion UIs, chosen over a plain checkbox
 * because it forces the user to actually read and reproduce something
 * specific to their account rather than blindly toggle a box.
 *
 * On a 204 from `/api/users/me`'s `DELETE` (the FE-17 BFF proxy — see that
 * route's doc comment for why no separate logout call is needed), the
 * session is already over server-side; this only needs to leave the client
 * in the same state `use-logout.ts` does: navigate home and `router.refresh()`
 * so the nav re-renders against the now-cleared cookies.
 */
export function DeleteAccountDialog({ username }: { username: string }) {
  const t = useTranslations("Settings.deleteAccount");
  const router = useRouter();

  const [open, setOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [state, setState] = useState<SubmitState>("idle");

  const confirmMatches = confirmText === username;

  function resetDialogState() {
    setConfirmText("");
    setState("idle");
  }

  async function handleConfirm() {
    if (!confirmMatches) {
      return;
    }

    setState("submitting");

    let response: Response;
    try {
      response = await fetch("/api/users/me", { method: "DELETE" });
    } catch {
      setState("error");
      return;
    }

    if (response.status === 204) {
      setOpen(false);
      toast.success(t("success"));
      router.push("/");
      router.refresh();
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
        <Button type="button" variant="destructive" size="sm">
          {t("openDialog")}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("heading")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="delete-account-confirm">{t("confirmLabel", { username })}</Label>
          <Input
            id="delete-account-confirm"
            autoComplete="off"
            value={confirmText}
            onChange={(event) => setConfirmText(event.target.value)}
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
            disabled={!confirmMatches || state === "submitting"}
            onClick={handleConfirm}
          >
            {state === "submitting" ? t("confirming") : t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
