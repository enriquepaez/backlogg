import { NextResponse } from "next/server";

import type { components } from "@backlogg/api-client";

import { isCatalogType } from "@/lib/catalog-types";
import { getApiClient } from "@/lib/auth/session";
import { env } from "@/lib/env";

type CatalogEditIn = components["schemas"]["CatalogEditIn"];
type RouteParams = { params: Promise<{ type: string; slug: string }> };

function isNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

function isNullableStringArray(value: unknown): value is string[] | null | undefined {
  return (
    value === undefined ||
    value === null ||
    (Array.isArray(value) && value.every((entry) => typeof entry === "string"))
  );
}

/**
 * PATCH /api/admin/{type}/{slug}
 *
 * Proxies `PATCH /v1/admin/{type}/{slug}` (feature 49, `docs/api.md`): the
 * only write path for movies/series/books/games — corrects a subset of
 * fields and locks each touched field against the next nightly sync. Same
 * X-API-Key-only auth pattern as `../../users/route.ts` (this app's own
 * `ADMIN_API_KEY`, `@/lib/env`, read server-side ONLY and injected as
 * `X-API-Key`) — unlike grant-admin/revoke-admin, `docs/api.md` documents
 * this endpoint as needing only the shared secret, no caller Bearer token,
 * so this route does not use `apiFetch`.
 *
 * `@/lib/admin-catalog.ts` (`fetchAdminCatalogItem`), the caller used by
 * `AdminCatalogEditDialog` to hydrate its form, also sends an EMPTY body
 * (`{}`) through this same route to "peek" at an item's current state
 * (including `locked_fields`, which has no dedicated GET) — see that
 * module's doc comment for why that is safe and intentional.
 *
 * The body is re-built here from known keys only (same defensive parsing
 * style as `../../users/me/route.ts`) rather than forwarded verbatim, so a
 * malformed client payload never reaches the backend as anything other than
 * a deliberate `CatalogEditIn` shape.
 *
 * Status mapping: this app's own `ADMIN_API_KEY` unset -> 503; unrecognized
 * `type` segment -> 400 (never reaches the backend); backend 401 -> 401;
 * backend 404 (unknown slug) -> 404; backend 422 (non-editable field, empty
 * `title`, or unknown `unlock_fields` entry) -> 422; backend 503 -> 503;
 * anything else -> 502.
 */
export async function PATCH(request: Request, { params }: RouteParams): Promise<NextResponse> {
  const { type, slug } = await params;
  if (!isCatalogType(type)) {
    return NextResponse.json({ error: "invalid_type" }, { status: 400 });
  }

  let apiKey: string;
  try {
    apiKey = env.ADMIN_API_KEY;
  } catch {
    return NextResponse.json({ error: "not_configured" }, { status: 503 });
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }

  const source = (raw ?? {}) as Record<string, unknown>;
  const body: CatalogEditIn = {};

  if ("title" in source) {
    if (!isNullableString(source.title)) {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    body.title = source.title ?? null;
  }
  if ("poster_url" in source) {
    if (!isNullableString(source.poster_url)) {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    body.poster_url = source.poster_url ?? null;
  }
  if ("release_date" in source) {
    if (!isNullableString(source.release_date)) {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    body.release_date = source.release_date ?? null;
  }
  if ("first_air_date" in source) {
    if (!isNullableString(source.first_air_date)) {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    body.first_air_date = source.first_air_date ?? null;
  }
  if ("first_publish_date" in source) {
    if (!isNullableString(source.first_publish_date)) {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    body.first_publish_date = source.first_publish_date ?? null;
  }
  if ("genres" in source) {
    if (!isNullableStringArray(source.genres)) {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    body.genres = source.genres ?? null;
  }
  if ("unlock_fields" in source) {
    if (!isNullableStringArray(source.unlock_fields)) {
      return NextResponse.json({ error: "invalid_body" }, { status: 400 });
    }
    body.unlock_fields = source.unlock_fields ?? null;
  }

  try {
    const { data, response } = await getApiClient().PATCH("/v1/admin/{type}/{slug}", {
      params: { header: { "x-api-key": apiKey }, path: { type, slug } },
      body,
    });

    if (response.status === 200 && data) {
      return NextResponse.json(data, { status: 200 });
    }
    if (response.status === 401) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    if (response.status === 404) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }
    if (response.status === 422) {
      return NextResponse.json({ error: "validation_error" }, { status: 422 });
    }
    if (response.status === 503) {
      return NextResponse.json({ error: "not_configured" }, { status: 503 });
    }

    return NextResponse.json({ error: "admin_catalog_edit_failed" }, { status: 502 });
  } catch (error) {
    console.error("PATCH /api/admin/[type]/[slug]: failed to reach the API", error);
    return NextResponse.json({ error: "admin_catalog_edit_failed" }, { status: 502 });
  }
}
