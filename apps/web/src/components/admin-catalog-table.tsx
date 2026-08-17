"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { AdminCatalogEditDialog } from "@/components/admin-catalog-edit-dialog";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ADMIN_CATALOG_DATE_FIELD, type AdminCatalogItem } from "@/lib/admin-catalog";
import type { CatalogListItem, CatalogType } from "@/lib/catalog-types";

export type AdminCatalogTableProps = {
  type: CatalogType;
  items: CatalogListItem[];
  /** Already-localized label for this type's date column (`Admin.catalog.dateLabel.{type}`). */
  dateLabel: string;
};

/**
 * Real `<table>` listing for `/admin/{movies,series,books,games}` (FE-34),
 * same shadcn `Table` primitive `/admin/users` introduced (FE-33) — an
 * "Edit" action per row opens `AdminCatalogEditDialog`.
 *
 * Holds its own `rows` state, seeded from the server-fetched `items` prop
 * (`listCatalog`, `@/lib/catalog.ts` — same data source `/browse/[type]`
 * uses, FE-9), so a successful save can "refresh the row in place" with the
 * PATCH response (acceptance criterion 3) without a full page reload.
 * Re-seeds `rows` whenever `items` itself changes (a new reference on every
 * filter/sort/page navigation, since that's a fresh server render) using the
 * "adjusting state when a prop changes" pattern React's own docs recommend
 * (comparing against the previous prop value during render, not inside a
 * `useEffect`) — without it, `rows` would keep showing a stale page after
 * the URL's filters change, since `useState(items)` alone only reads its
 * argument on the very first render.
 *
 * The list endpoints (`GET /v1/{type}`) return `genres` as SLUGS
 * (`CatalogListItem.genres`), but a successful edit's response
 * (`CatalogEditOut.genres`) returns genre NAMES (`docs/api.md`) — this table
 * just joins whichever array it currently has for that row into a plain
 * comma-separated string, so a post-save row briefly displays names instead
 * of slugs. Cosmetic only (both are just informational text in this
 * column), not worth a second fetch to reconcile.
 */
export function AdminCatalogTable({ type, items, dateLabel }: AdminCatalogTableProps) {
  const t = useTranslations("Admin.catalog");
  const [rows, setRows] = useState(items);
  const [prevItems, setPrevItems] = useState(items);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);

  if (items !== prevItems) {
    setPrevItems(items);
    setRows(items);
  }

  const editingItem = rows.find((row) => row.slug === editingSlug) ?? null;
  const dateField = ADMIN_CATALOG_DATE_FIELD[type];

  function handleSaved(saved: AdminCatalogItem) {
    setRows((current) =>
      current.map((row) =>
        row.slug === saved.slug
          ? {
              ...row,
              title: saved.title,
              poster_url: saved.poster_url,
              release_date: saved[dateField] ?? null,
              genres: saved.genres,
            }
          : row,
      ),
    );
    setEditingSlug(null);
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("columns.item")}</TableHead>
            <TableHead>{t("columns.genres")}</TableHead>
            <TableHead>{dateLabel}</TableHead>
            <TableHead>{t("columns.rating")}</TableHead>
            <TableHead>
              <span className="sr-only">{t("columns.actions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((item) => (
            <TableRow key={item.slug}>
              <TableCell className="font-medium text-foreground">{item.title}</TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {item.genres.length > 0 ? item.genres.join(", ") : t("emptyValue")}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {item.release_date ?? t("emptyValue")}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {item.rating_external !== null ? item.rating_external.toFixed(1) : t("emptyValue")}
              </TableCell>
              <TableCell>
                <Button type="button" variant="outline" size="sm" onClick={() => setEditingSlug(item.slug)}>
                  {t("editAction")}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {editingItem ? (
        <AdminCatalogEditDialog
          type={type}
          slug={editingItem.slug}
          fallbackTitle={editingItem.title}
          dateLabel={dateLabel}
          onClose={() => setEditingSlug(null)}
          onSaved={handleSaved}
        />
      ) : null}
    </>
  );
}
