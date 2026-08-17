import type { components } from "@backlogg/api-client";

import type { CatalogType } from "./catalog-types";

/**
 * Client-safe (no `server-only`) helpers for the admin catalog backoffice
 * (FE-34): editing movies/series/books/games via `PATCH /v1/admin/{type}/{slug}`
 * (feature 49, `docs/api.md`), proxied by `@/app/api/admin/[type]/[slug]/route.ts`.
 * Mirrors the shape of `@/lib/admin-user-actions.ts` (FE-30/33): plain
 * `fetch()` against this app's own `/api/admin/**`, normalized into a
 * discriminated result — no `server-only` import so `admin-catalog-edit-dialog.tsx`
 * ("use client") can import it directly.
 */

/** The single date column exposed per type (`docs/api.md`'s editable-fields table). */
export type AdminCatalogDateField = "release_date" | "first_air_date" | "first_publish_date";

export const ADMIN_CATALOG_DATE_FIELD: Record<CatalogType, AdminCatalogDateField> = {
  movie: "release_date",
  series: "first_air_date",
  book: "first_publish_date",
  game: "release_date",
};

/** The four static `/admin/*` catalog routes FE-33 stubbed and this feature fills in. */
export type AdminCatalogBasePath = "/admin/movies" | "/admin/series" | "/admin/books" | "/admin/games";

export const ADMIN_CATALOG_BASE_PATH: Record<CatalogType, AdminCatalogBasePath> = {
  movie: "/admin/movies",
  series: "/admin/series",
  book: "/admin/books",
  game: "/admin/games",
};

/** `CatalogEditOut` — the item's current admin-editable state, including `locked_fields`. */
export type AdminCatalogItem = components["schemas"]["CatalogEditOut"];

/** `CatalogEditIn` — a PATCH payload. Only fields the admin actually touched should be set. */
export type AdminCatalogEditPayload = components["schemas"]["CatalogEditIn"];

export type AdminCatalogErrorReason =
  | "unauthorized"
  | "not_found"
  | "not_configured"
  | "validation"
  | "unknown";

function reasonFromStatus(status: number): AdminCatalogErrorReason {
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status === 503) return "not_configured";
  if (status === 422) return "validation";
  return "unknown";
}

export type AdminCatalogResult =
  | { ok: true; item: AdminCatalogItem }
  | { ok: false; reason: AdminCatalogErrorReason };

async function patchAdminCatalogItem(
  type: CatalogType,
  slug: string,
  body: AdminCatalogEditPayload,
): Promise<AdminCatalogResult> {
  try {
    const response = await fetch(`/api/admin/${type}/${encodeURIComponent(slug)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.status === 200) {
      const item = (await response.json()) as AdminCatalogItem;
      return { ok: true, item };
    }
    return { ok: false, reason: reasonFromStatus(response.status) };
  } catch {
    return { ok: false, reason: "unknown" };
  }
}

/**
 * "Reads" one item's current admin-editable state, including `locked_fields`,
 * by sending an EMPTY `CatalogEditIn` body (`{}`) through
 * `PATCH /api/admin/{type}/{slug}`.
 *
 * There is no dedicated GET for this data — `locked_fields` is only ever
 * returned by `CatalogEditOut`, the PATCH endpoint's own response
 * (`docs/api.md`, `docs/schema.md`'s `locked_fields` section). An empty body
 * means nothing is "set" from Pydantic's `exclude_unset` point of view
 * (`backlogg/admin/service.py::edit_catalog_item`: `provided =
 * payload.model_dump(exclude_unset=True)` is `{}`), so the service applies
 * zero edits and zero (un)locks, and just echoes back the item's current
 * title/poster_url/date/genres/locked_fields — at the cost of one harmless
 * no-op `UPDATE`+commit (`backlogg/movies/repository.py::admin_update_movie`
 * and its series/book/game siblings are all no-ops on an empty `updates`
 * dict). Used by `admin-catalog-edit-dialog.tsx` to hydrate the edit form
 * when it opens.
 */
export function fetchAdminCatalogItem(type: CatalogType, slug: string): Promise<AdminCatalogResult> {
  return patchAdminCatalogItem(type, slug, {});
}

/**
 * Saves a real edit. `payload` should only contain the fields the admin
 * actually changed (a dirty diff — see `admin-catalog-edit-dialog.tsx`) plus
 * `unlock_fields` for any field the admin explicitly chose to release back
 * to sync control. Touching ANY field here (re-)locks it against the next
 * nightly sync (`CatalogEditIn`'s own doc comment) — omitting an untouched
 * field is what keeps its lock state unchanged.
 */
export function saveAdminCatalogItem(
  type: CatalogType,
  slug: string,
  payload: AdminCatalogEditPayload,
): Promise<AdminCatalogResult> {
  return patchAdminCatalogItem(type, slug, payload);
}
