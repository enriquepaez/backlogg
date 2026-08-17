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
} from "@/components/ui/dialog";
import {
  type AdminUserAction,
  callAdminUserAction,
  type RoleGrantResult,
  type UserModerationResult,
} from "@/lib/admin-user-actions";

export type AdminUserActionsPanelProps = {
  username: string;
  initialIsAdmin: boolean;
  initialIsBanned: boolean;
  isTargetSuperadmin: boolean;
  callerIsSuperadmin: boolean;
};

/** A ban/revoke-admin confirmation pending the admin's click on the dialog's confirm button. */
type ConfirmAction = "ban" | "revoke-admin";

/**
 * Client Component (FE-33): the role/ban badges + moderation actions for
 * `/admin/users/{username}`'s detail page. Owns the target user's
 * `is_admin`/`is_banned` state locally (seeded from the Server Component
 * page's own `getAdminUserDetail` call), so a successful action can "patch
 * the page in place without a full reload" — this component IS that
 * mutable slice of the page, badges and buttons together, rather than
 * splitting the two across a server-rendered badge strip and a client-side
 * button row that would need to somehow stay in sync.
 *
 * `is_superadmin` (`isTargetSuperadmin`) is NOT part of this local state —
 * neither `grant-admin` nor `revoke-admin` can change it (`docs/api.md`), so
 * it stays a plain prop, same as every other read-only profile field this
 * page renders elsewhere.
 *
 * Ban and revoke-admin require a confirmation dialog (destructive/security-
 * sensitive); unban and grant-admin do not — same asymmetry the FE-30/FE-33
 * table version used before actions moved here. A single `Dialog`, keyed by
 * `confirmAction`, covers both cases (only one action targets this one user
 * at a time, so there is never more than one confirmation in flight).
 *
 * Grant/revoke-admin only renders when `callerIsSuperadmin` is `true`
 * (sourced from the page's own `getCurrentUser()` call, `UserMeOut.is_superadmin`)
 * — a UX convenience only, same as before: the backend's own 403 (mapped to
 * `errors.forbidden` below) is the real authorization boundary.
 *
 * Reuses `callAdminUserAction` (`@/lib/admin-user-actions.ts`) as-is — the
 * fetch/status-mapping logic itself is not reimplemented here, only the
 * per-user (rather than per-row) state it now drives.
 */
export function AdminUserActionsPanel({
  username,
  initialIsAdmin,
  initialIsBanned,
  isTargetSuperadmin,
  callerIsSuperadmin,
}: AdminUserActionsPanelProps) {
  const t = useTranslations("Admin.userDetail");

  const [isAdmin, setIsAdmin] = useState(initialIsAdmin);
  const [isBanned, setIsBanned] = useState(initialIsBanned);
  const [pending, setPending] = useState(false);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);

  function applyActionResult(action: AdminUserAction, data: UserModerationResult | RoleGrantResult) {
    if (action === "ban" || action === "unban") {
      setIsBanned((data as UserModerationResult).is_banned);
    } else {
      setIsAdmin((data as RoleGrantResult).is_admin);
    }
  }

  async function runAction(action: AdminUserAction) {
    if (pending) return;
    setPending(true);

    const result = await callAdminUserAction(action, username);

    setPending(false);
    if (!result.ok) {
      toast.error(t(`actions.errors.${result.reason}`));
      return;
    }

    applyActionResult(action, result.data);
    const successKey =
      action === "ban"
        ? "banned"
        : action === "unban"
          ? "unbanned"
          : action === "grant-admin"
            ? "granted"
            : "revoked";
    toast.success(t(`actions.success.${successKey}`));
  }

  function handleUnban() {
    void runAction("unban");
  }

  function handleGrant() {
    void runAction("grant-admin");
  }

  function handleConfirm() {
    if (!confirmAction) return;
    setConfirmAction(null);
    void runAction(confirmAction);
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {isTargetSuperadmin ? (
          <span className="w-fit rounded-full bg-purple-500/10 px-2.5 py-0.5 text-xs font-medium text-purple-600">
            {t("badges.superadmin")}
          </span>
        ) : isAdmin ? (
          <span className="w-fit rounded-full bg-blue-500/10 px-2.5 py-0.5 text-xs font-medium text-blue-600">
            {t("badges.admin")}
          </span>
        ) : null}
        {isBanned ? (
          <span className="w-fit rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs font-medium text-destructive">
            {t("badges.banned")}
          </span>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        {callerIsSuperadmin ? (
          isAdmin ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={pending}
              onClick={() => setConfirmAction("revoke-admin")}
            >
              {pending ? t("actions.submitting") : t("actions.revokeAction")}
            </Button>
          ) : (
            <Button type="button" variant="outline" size="sm" disabled={pending} onClick={handleGrant}>
              {pending ? t("actions.submitting") : t("actions.grantAction")}
            </Button>
          )
        ) : null}

        {isBanned ? (
          <Button type="button" variant="outline" size="sm" disabled={pending} onClick={handleUnban}>
            {pending ? t("actions.submitting") : t("actions.unbanAction")}
          </Button>
        ) : (
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={pending}
            onClick={() => setConfirmAction("ban")}
          >
            {pending ? t("actions.submitting") : t("actions.banAction")}
          </Button>
        )}
      </div>

      <Dialog open={confirmAction !== null} onOpenChange={(open) => !open && setConfirmAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirmAction === "ban" ? t("actions.banDialog.heading") : t("actions.revokeDialog.heading")}
            </DialogTitle>
            <DialogDescription>
              {confirmAction
                ? t(
                    confirmAction === "ban" ? "actions.banDialog.description" : "actions.revokeDialog.description",
                    { username },
                  )
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {confirmAction === "ban" ? t("actions.banDialog.cancel") : t("actions.revokeDialog.cancel")}
              </Button>
            </DialogClose>
            <Button type="button" variant="destructive" onClick={handleConfirm}>
              {confirmAction === "ban" ? t("actions.banDialog.confirm") : t("actions.revokeDialog.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
