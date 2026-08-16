"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Known error reasons relayed 1:1 by the BFF routes this panel calls. */
type ErrorReason =
  | "missingUsername"
  | "not_found"
  | "forbidden"
  | "unauthorized"
  | "not_configured"
  | "unknown";

function reasonFromStatus(status: number): ErrorReason {
  if (status === 403) return "forbidden";
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status === 503) return "not_configured";
  return "unknown";
}

/**
 * User ban/unban section (FE-30): bans or unbans a username via
 * `POST /api/admin/users/{username}/ban` / `/unban`
 * (`@/app/api/admin/users/[username]/ban/route.ts` and its `unban`
 * sibling), the BFF routes that inject the shared `X-API-Key` server-side —
 * this component never sees it. Unlike `AdminReportsPanel`'s report queue,
 * there is no list to browse here: the admin looks up a specific account by
 * username, same "act on a known identifier" shape as `AdminRolesPanel`
 * below.
 *
 * Ban requires a confirmation dialog (destructive, same "type-free confirm"
 * pattern as `DeleteAccountDialog` minus the typed confirmation — a ban is
 * reversible via unban, unlike account deletion, so a plain confirm click is
 * enough); unban does not, matching the plan in `progress/current.md`.
 * The result of the last action (`UserModerationOut.is_banned`) is kept in
 * local state and rendered as an inline status line — this IS the "refresh
 * after each action" requirement for this component: there is no list
 * fetched on mount to refetch, the action's own response is the freshest
 * available truth about that username.
 */
function AdminUserModerationSection() {
  const t = useTranslations("Admin.moderation.users");

  const [username, setUsername] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [status, setStatus] = useState<{ username: string; isBanned: boolean } | null>(null);
  const [error, setError] = useState<ErrorReason | null>(null);

  async function callAction(action: "ban" | "unban", target: string) {
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`/api/admin/users/${encodeURIComponent(target)}/${action}`, {
        method: "POST",
      });
      if (response.status === 200) {
        const data = (await response.json()) as { username: string; is_banned: boolean };
        setStatus({ username: data.username, isBanned: data.is_banned });
        toast.success(action === "ban" ? t("success.banned") : t("success.unbanned"));
      } else {
        setError(reasonFromStatus(response.status));
      }
    } catch {
      setError("unknown");
    } finally {
      setSubmitting(false);
    }
  }

  function handleUnban() {
    const target = username.trim();
    if (!target) {
      setError("missingUsername");
      return;
    }
    void callAction("unban", target);
  }

  function handleConfirmBan() {
    const target = username.trim();
    setDialogOpen(false);
    void callAction("ban", target);
  }

  function openBanDialog() {
    const target = username.trim();
    if (!target) {
      setError("missingUsername");
      return;
    }
    setDialogOpen(true);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">{t("heading")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="moderation-ban-username">{t("usernameLabel")}</Label>
          <Input
            id="moderation-ban-username"
            placeholder={t("usernamePlaceholder")}
            value={username}
            onChange={(event) => {
              setUsername(event.target.value);
              setError(null);
            }}
          />
        </div>

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {t(`errors.${error}`)}
          </p>
        ) : null}

        {status ? (
          <p className="text-sm text-muted-foreground">
            {t(status.isBanned ? "statusBanned" : "statusNotBanned", { username: status.username })}
          </p>
        ) : null}

        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" size="sm" disabled={submitting} onClick={handleUnban}>
            {submitting ? t("submitting") : t("unbanAction")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={submitting}
            onClick={openBanDialog}
          >
            {submitting ? t("submitting") : t("banAction")}
          </Button>
        </div>
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("banDialog.heading")}</DialogTitle>
            <DialogDescription>
              {t("banDialog.description", { username: username.trim() })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t("banDialog.cancel")}
              </Button>
            </DialogClose>
            <Button type="button" variant="destructive" onClick={handleConfirmBan}>
              {t("banDialog.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/**
 * Admin role grant/revoke section (FE-30): grants or revokes `is_admin` via
 * `POST /api/admin/users/{username}/grant-admin` / `/revoke-admin`
 * (`@/app/api/admin/users/[username]/grant-admin/route.ts` and its
 * `revoke-admin` sibling) — the one pair of BFF routes under
 * `src/app/api/admin/**` that also forwards the caller's own Bearer token
 * (see that route's doc comment), because the backend itself checks
 * `is_superadmin` server-side on top of the shared `X-API-Key`.
 *
 * This component is only ever mounted by `AdminModerationPanel` when the
 * CALLER's own `isSuperadmin` prop (sourced from `getCurrentUser()`'s
 * `UserMeOut.is_superadmin` — never present on the public `UserOut`, see
 * `docs/api.md`) is `true` — a normal admin (`is_admin` but not
 * `is_superadmin`) never sees this section rendered at all, not even
 * disabled. This is a UX convenience only: the backend's own 403 (handled
 * below via `forbidden`) is the real authorization boundary, enforced
 * server-side regardless of what this component renders.
 *
 * Revoke requires a confirmation dialog (mirrors `AdminUserModerationSection`'s
 * ban dialog); grant does not. Same local "last action result is the
 * freshest truth" status line as that section — there is no list to refetch.
 */
function AdminRolesSection() {
  const t = useTranslations("Admin.moderation.roles");

  const [username, setUsername] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [status, setStatus] = useState<{ username: string; isAdmin: boolean } | null>(null);
  const [error, setError] = useState<ErrorReason | null>(null);

  async function callAction(action: "grant-admin" | "revoke-admin", target: string) {
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`/api/admin/users/${encodeURIComponent(target)}/${action}`, {
        method: "POST",
      });
      if (response.status === 200) {
        const data = (await response.json()) as { username: string; is_admin: boolean };
        setStatus({ username: data.username, isAdmin: data.is_admin });
        toast.success(action === "grant-admin" ? t("success.granted") : t("success.revoked"));
      } else {
        setError(reasonFromStatus(response.status));
      }
    } catch {
      setError("unknown");
    } finally {
      setSubmitting(false);
    }
  }

  function handleGrant() {
    const target = username.trim();
    if (!target) {
      setError("missingUsername");
      return;
    }
    void callAction("grant-admin", target);
  }

  function openRevokeDialog() {
    const target = username.trim();
    if (!target) {
      setError("missingUsername");
      return;
    }
    setDialogOpen(true);
  }

  function handleConfirmRevoke() {
    const target = username.trim();
    setDialogOpen(false);
    void callAction("revoke-admin", target);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">{t("heading")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="moderation-role-username">{t("usernameLabel")}</Label>
          <Input
            id="moderation-role-username"
            placeholder={t("usernamePlaceholder")}
            value={username}
            onChange={(event) => {
              setUsername(event.target.value);
              setError(null);
            }}
          />
        </div>

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {t(`errors.${error}`)}
          </p>
        ) : null}

        {status ? (
          <p className="text-sm text-muted-foreground">
            {t(status.isAdmin ? "statusAdmin" : "statusNotAdmin", { username: status.username })}
          </p>
        ) : null}

        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={submitting}
            onClick={openRevokeDialog}
          >
            {submitting ? t("submitting") : t("revokeAction")}
          </Button>
          <Button type="button" variant="outline" size="sm" disabled={submitting} onClick={handleGrant}>
            {submitting ? t("submitting") : t("grantAction")}
          </Button>
        </div>
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("revokeDialog.heading")}</DialogTitle>
            <DialogDescription>
              {t("revokeDialog.description", { username: username.trim() })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t("revokeDialog.cancel")}
              </Button>
            </DialogClose>
            <Button type="button" variant="destructive" onClick={handleConfirmRevoke}>
              {t("revokeDialog.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/**
 * Moderation actions panel (FE-30): mounted below `AdminReportsPanel` on
 * `/admin` (`@/app/[locale]/admin/page.tsx`). Bundles the two username-keyed
 * moderation actions that aren't tied to the report queue itself (hide/unhide
 * lives inline in `AdminReportsPanel`, next to each reported review, since it
 * acts on a specific rating rather than a username):
 *
 * - `AdminUserModerationSection`: ban/unban, always rendered.
 * - `AdminRolesSection`: grant/revoke admin, rendered ONLY when `isSuperadmin`
 *   is `true` — the page passes `user.is_superadmin` straight from
 *   `getCurrentUser()`'s `UserMeOut` (server-side, `docs/api.md`: never on the
 *   public `UserOut`). A regular admin never sees this section mounted at
 *   all, not merely disabled.
 */
export function AdminModerationPanel({ isSuperadmin }: { isSuperadmin: boolean }) {
  return (
    <div className="flex flex-col gap-4 sm:grid sm:grid-cols-2 sm:items-start sm:gap-4">
      <AdminUserModerationSection />
      {isSuperadmin ? <AdminRolesSection /> : null}
    </div>
  );
}
