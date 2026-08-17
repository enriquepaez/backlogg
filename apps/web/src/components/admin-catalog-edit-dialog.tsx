"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ADMIN_CATALOG_DATE_FIELD,
  fetchAdminCatalogItem,
  saveAdminCatalogItem,
  type AdminCatalogEditPayload,
  type AdminCatalogItem,
} from "@/lib/admin-catalog";
import type { CatalogType } from "@/lib/catalog-types";

export type AdminCatalogEditDialogProps = {
  type: CatalogType;
  slug: string;
  /** Title from the table row, shown in the heading while the real item is still loading. */
  fallbackTitle: string;
  /** Already-localized label for this type's date column (`dateLabel.{type}`, resolved by the caller — see `admin-catalog-table.tsx`). */
  dateLabel: string;
  onClose: () => void;
  onSaved: (item: AdminCatalogItem) => void;
};

type FormValues = {
  title: string;
  posterUrl: string;
  date: string;
  genres: string;
};

type LoadState =
  | { status: "loading" }
  | { status: "loaded"; item: AdminCatalogItem }
  | { status: "error"; reason: "unauthorized" | "not_found" | "not_configured" | "unknown" };

/**
 * Edit form for one catalog item (FE-34). `AdminCatalogTable` mounts this
 * only while a row's "Edit" action is active.
 *
 * On mount, fetches the item's current admin-editable state — title,
 * poster_url, this type's own date column, genres, `locked_fields` — via an
 * EMPTY-body `PATCH` (`fetchAdminCatalogItem`, `@/lib/admin-catalog.ts`);
 * see that module's doc comment for why an empty body is the intended way
 * to "read" this state (there is no dedicated GET for it). Once loaded, the
 * form is seeded with `reset()` so react-hook-form's `formState.dirtyFields`
 * tells apart fields the admin actually touched from ones merely
 * redisplayed — only dirty fields are sent back on save, since touching ANY
 * field in the PATCH payload (re-)locks it against the next nightly sync
 * (`CatalogEditIn`'s own doc comment, `docs/api.md`), and this dialog must
 * not lock fields the admin never meant to change.
 *
 * Each of the four editable fields shows a "locked" badge plus an "unlock"
 * checkbox when `locked_fields` already contains it — checking it adds the
 * field name to `unlock_fields` on the next save, independent of whether
 * that field's value is also edited in the same request (a field present in
 * both ends up unlocked, not locked — same overlap rule `CatalogEditIn`
 * documents).
 *
 * `title` is the only field the backend itself validates (non-empty/
 * non-whitespace) — mirrored here with a plain react-hook-form `validate`
 * rule so the common case never round-trips to a 422 at all. Every other
 * field is unconstrained by the backend, and the edit/`unlock_fields` keys
 * sent are always a subset of this type's editable set by construction (the
 * form only ever renders those four fields) — so a 422 from `saveAdminCatalogItem`
 * should not be reachable through this UI; when it defensively does happen,
 * it surfaces as the same generic `errors.validation` toast every other
 * failure reason uses, same fallback pattern `account-profile-form.tsx`
 * already established for 422s in this app.
 */
export function AdminCatalogEditDialog({
  type,
  slug,
  fallbackTitle,
  dateLabel,
  onClose,
  onSaved,
}: AdminCatalogEditDialogProps) {
  const t = useTranslations("Admin.catalog.dialog");
  const dateField = ADMIN_CATALOG_DATE_FIELD[type];

  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [unlockedFields, setUnlockedFields] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, dirtyFields, isDirty },
  } = useForm<FormValues>({
    defaultValues: { title: fallbackTitle, posterUrl: "", date: "", genres: "" },
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const result = await fetchAdminCatalogItem(type, slug);
      if (cancelled) return;

      if (!result.ok) {
        setState({ status: "error", reason: result.reason === "validation" ? "unknown" : result.reason });
        return;
      }

      setState({ status: "loaded", item: result.item });
      reset({
        title: result.item.title,
        posterUrl: result.item.poster_url ?? "",
        date: result.item[dateField] ?? "",
        genres: result.item.genres.join(", "),
      });
    }

    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, slug]);

  function isLocked(field: string): boolean {
    return state.status === "loaded" && state.item.locked_fields.includes(field);
  }

  function toggleUnlock(field: string) {
    setUnlockedFields((current) => {
      const next = new Set(current);
      if (next.has(field)) {
        next.delete(field);
      } else {
        next.add(field);
      }
      return next;
    });
  }

  async function onSubmit(values: FormValues) {
    if (state.status !== "loaded") return;

    const payload: AdminCatalogEditPayload = {};
    if (dirtyFields.title) payload.title = values.title.trim();
    if (dirtyFields.posterUrl) payload.poster_url = values.posterUrl.trim() || null;
    if (dirtyFields.date) payload[dateField] = values.date.trim() || null;
    if (dirtyFields.genres) {
      payload.genres = values.genres
        .split(",")
        .map((name) => name.trim())
        .filter((name) => name.length > 0);
    }
    if (unlockedFields.size > 0) {
      payload.unlock_fields = Array.from(unlockedFields);
    }

    if (Object.keys(payload).length === 0) {
      return;
    }

    setSubmitting(true);
    const result = await saveAdminCatalogItem(type, slug, payload);
    setSubmitting(false);

    if (!result.ok) {
      toast.error(t(`errors.${result.reason}`));
      return;
    }

    toast.success(t("success"));
    onSaved(result.item);
  }

  const hasChanges = isDirty || unlockedFields.size > 0;
  const headingTitle = state.status === "loaded" ? state.item.title : fallbackTitle;

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("heading", { title: headingTitle })}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        {state.status === "loading" ? (
          <p role="status" className="text-sm text-muted-foreground">
            {t("loading")}
          </p>
        ) : state.status === "error" ? (
          <p role="alert" className="text-sm text-destructive">
            {t(`errors.${state.reason}`)}
          </p>
        ) : (
          <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
            <FieldRow
              id="admin-catalog-edit-title"
              label={t("fields.title")}
              locked={isLocked("title")}
              unlocked={unlockedFields.has("title")}
              onToggleUnlock={() => toggleUnlock("title")}
              lockedBadge={t("lockedBadge")}
              unlockLabel={t("unlockLabel")}
              error={errors.title ? t("errors.title") : undefined}
            >
              <Input
                id="admin-catalog-edit-title"
                aria-invalid={!!errors.title}
                {...register("title", { validate: (value) => value.trim().length > 0 })}
              />
            </FieldRow>

            <FieldRow
              id="admin-catalog-edit-poster"
              label={t("fields.posterUrl")}
              locked={isLocked("poster_url")}
              unlocked={unlockedFields.has("poster_url")}
              onToggleUnlock={() => toggleUnlock("poster_url")}
              lockedBadge={t("lockedBadge")}
              unlockLabel={t("unlockLabel")}
            >
              <Input id="admin-catalog-edit-poster" {...register("posterUrl")} />
            </FieldRow>

            <FieldRow
              id="admin-catalog-edit-date"
              label={dateLabel}
              locked={isLocked(dateField)}
              unlocked={unlockedFields.has(dateField)}
              onToggleUnlock={() => toggleUnlock(dateField)}
              lockedBadge={t("lockedBadge")}
              unlockLabel={t("unlockLabel")}
            >
              <Input id="admin-catalog-edit-date" type="date" {...register("date")} />
            </FieldRow>

            <FieldRow
              id="admin-catalog-edit-genres"
              label={t("fields.genres")}
              locked={isLocked("genres")}
              unlocked={unlockedFields.has("genres")}
              onToggleUnlock={() => toggleUnlock("genres")}
              lockedBadge={t("lockedBadge")}
              unlockLabel={t("unlockLabel")}
            >
              <Input id="admin-catalog-edit-genres" {...register("genres")} />
            </FieldRow>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={onClose}>
                {t("cancel")}
              </Button>
              <Button type="submit" disabled={submitting || !hasChanges}>
                {submitting ? t("saving") : t("save")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function FieldRow({
  id,
  label,
  children,
  locked,
  unlocked,
  onToggleUnlock,
  lockedBadge,
  unlockLabel,
  error,
}: {
  id: string;
  label: string;
  children: ReactNode;
  locked: boolean;
  unlocked: boolean;
  onToggleUnlock: () => void;
  lockedBadge: string;
  unlockLabel: string;
  error?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>{label}</Label>
        {locked ? (
          <span className="w-fit rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-600">
            {lockedBadge}
          </span>
        ) : null}
      </div>
      {children}
      {locked ? (
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={unlocked}
            onChange={onToggleUnlock}
            className="size-3.5 rounded border-input"
          />
          {unlockLabel}
        </label>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
