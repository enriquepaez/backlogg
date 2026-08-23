import type { MetadataRoute } from "next";

import { getApiClient } from "@/lib/auth/session";
import { CATALOG_TYPES, type CatalogType } from "@/lib/catalog";
import { env } from "@/lib/env";
import { routing } from "@/i18n/routing";

/**
 * `GET /v1/{type}` sitemap fetch: page size for walking the catalog (FE-46).
 * 100 is the backend's own max `limit` (`docs/api.md`) — the largest page
 * size available, minimizing the number of round trips.
 */
const SITEMAP_PAGE_LIMIT = 100;

/**
 * Safety cap on the number of pages walked per catalog type. `500 *
 * SITEMAP_PAGE_LIMIT` = 50,000 URLs, which happens to match sitemaps.org's
 * own per-file limit (see `node_modules/next/dist/docs/.../sitemap.md`,
 * "Generating multiple sitemaps") — well beyond anything this catalog holds
 * today, and enough to stop an infinite loop if the backend ever returned an
 * inconsistent `total`.
 */
const MAX_PAGES_PER_TYPE = 500;

/**
 * ISR window for the sitemap fetch. Matches `BROWSE_REVALIDATE_SECONDS` in
 * `src/lib/catalog.ts`: the local catalog this reads only changes via the
 * nightly sync (GitHub Actions), so there is no value in refreshing more
 * often than that.
 */
const SITEMAP_REVALIDATE_SECONDS = 60 * 60 * 6; // 6h

/**
 * Forces this route to render per-request instead of being prerendered at
 * `next build` time. `getApiClient()` (via `session.ts`) throws if
 * `API_INTERNAL_URL` is unset, and CI's build step (`ci.yml`) never sets it —
 * there's no live backend available there, only during `pnpm --filter web
 * build`'s type/lint checks. Without this, Next tries to statically
 * pre-render `/sitemap.xml` at build time (it has no `cookies()`/other
 * dynamic API to opt out on its own, unlike `/recommendations` or
 * `/admin/*`) and the build fails outright instead of degrading. ISR restores
 * the same "don't refetch more than the nightly sync warrants" behavior at
 * request time via `SITEMAP_REVALIDATE_SECONDS` on each backend fetch below.
 */
export const dynamic = "force-dynamic";

type CatalogPage = { items: { slug: string }[]; total: number };

/**
 * One page of `GET /v1/{type}`, `slug`-only. Mirrors the per-type `switch` in
 * `listCatalog` (`src/lib/catalog.ts`) — that helper can't be reused directly
 * here because it hardcodes `BROWSE_PAGE_SIZE` (24) as `limit`, whereas the
 * sitemap wants the backend's max (`SITEMAP_PAGE_LIMIT`) to minimize round
 * trips. Returns `null` on any non-200 response so the caller can stop
 * paginating without throwing.
 */
async function fetchCatalogPage(
  client: ReturnType<typeof getApiClient>,
  type: CatalogType,
  page: number,
): Promise<CatalogPage | null> {
  const query = { page, limit: SITEMAP_PAGE_LIMIT };
  const next = { revalidate: SITEMAP_REVALIDATE_SECONDS };

  switch (type) {
    case "movie": {
      const { data, response } = await client.GET("/v1/movies", { params: { query }, next });
      return response.status === 200 && data ? data : null;
    }
    case "series": {
      const { data, response } = await client.GET("/v1/series", { params: { query }, next });
      return response.status === 200 && data ? data : null;
    }
    case "book": {
      const { data, response } = await client.GET("/v1/books", { params: { query }, next });
      return response.status === 200 && data ? data : null;
    }
    case "game": {
      const { data, response } = await client.GET("/v1/games", { params: { query }, next });
      return response.status === 200 && data ? data : null;
    }
  }
}

/**
 * Every slug for one catalog type, walking `GET /v1/{type}` page by page
 * until `total` is exhausted. Degrades to whatever was collected so far (or
 * an empty array) on a failed page or a network error — same spirit as the
 * rest of `src/lib/catalog.ts`'s public helpers: a partial or empty sitemap
 * for one type must not take down the whole `/sitemap.xml` response.
 */
async function fetchAllSlugs(
  client: ReturnType<typeof getApiClient>,
  type: CatalogType,
): Promise<string[]> {
  const slugs: string[] = [];

  try {
    for (let page = 1; page <= MAX_PAGES_PER_TYPE; page++) {
      const result = await fetchCatalogPage(client, type, page);
      if (!result || result.items.length === 0) {
        break;
      }
      slugs.push(...result.items.map((item) => item.slug));
      if (slugs.length >= result.total) {
        break;
      }
    }
  } catch (error) {
    // `type` is already the singular route segment ("movie"/"series"/"book"/
    // "game"); the backend's own path is `/v1/{plural}` (e.g. `/v1/movies`,
    // `/v1/series` — irregular, not just `+"s"`), so the message below names
    // the type rather than guessing its plural REST path.
    console.error(`sitemap: failed to walk the "${type}" catalog`, error);
  }

  return slugs;
}

/**
 * Absolute URL for one item detail page (`[locale]/[type]/[slug]/page.tsx`)
 * in the given locale.
 */
function itemUrl(locale: string, type: CatalogType, slug: string): string {
  return `${env.SITE_URL}/${locale}/${type}/${slug}`;
}

/**
 * Sitemap entries for one catalog type: one entry per slug, `url` pointing
 * at the default locale (`routing.defaultLocale`) with `alternates.languages`
 * covering every supported locale — same hreflang pattern documented in
 * `node_modules/next/dist/docs/.../sitemap.md` ("Generate a localized
 * Sitemap"). `localePrefix` is "always" (`src/i18n/routing.ts`), so every
 * locale — including the default — has its own prefixed URL.
 */
async function buildEntriesForType(
  client: ReturnType<typeof getApiClient>,
  type: CatalogType,
): Promise<MetadataRoute.Sitemap> {
  const slugs = await fetchAllSlugs(client, type);

  return slugs.map((slug) => ({
    url: itemUrl(routing.defaultLocale, type, slug),
    alternates: {
      languages: Object.fromEntries(
        routing.locales.map((locale) => [locale, itemUrl(locale, type, slug)]),
      ),
    },
  }));
}

/**
 * `src/app/sitemap.ts` (FE-46): entries for the public catalog's item detail
 * pages (movie/series/book/game), paginated from the API. Deliberately
 * covers ONLY those four routes — no user profiles (`/u/{username}`): there
 * is no backend endpoint to list every public username (see
 * `progress/current.md`'s "Fuera de scope" for the full rationale), and no
 * home/browse routes either, per this feature's acceptance criteria.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const client = getApiClient();
  const entriesByType = await Promise.all(
    CATALOG_TYPES.map((type) => buildEntriesForType(client, type)),
  );
  return entriesByType.flat();
}
