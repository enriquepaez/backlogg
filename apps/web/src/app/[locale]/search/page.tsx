import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CatalogCard } from "@/components/catalog-card";
import { RateLimitNotice } from "@/components/rate-limit-notice";
import { SearchControls } from "@/components/search-controls";
import { SearchPagination } from "@/components/search-pagination";
import { isCatalogType, type CatalogType } from "@/lib/catalog-types";
import { searchCatalog, toCatalogType } from "@/lib/search";

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseQuery(value: RawParam): string {
  const raw = firstValue(value);
  return raw ? raw.trim() : "";
}

function parseType(value: RawParam): CatalogType | undefined {
  const raw = firstValue(value);
  return raw && isCatalogType(raw) ? raw : undefined;
}

function parsePage(value: RawParam): number {
  const raw = firstValue(value);
  const parsed = raw ? Number.parseInt(raw, 10) : 1;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

/**
 * Static OG metadata for `/search` (FE-11) — unlike `/browse/{type}`'s
 * `generateMetadata` (FE-9), there is no single "the query" to interpolate:
 * `q` is free text supplied by the visitor, not a fixed content dimension
 * worth indexing per-value, so this is a single generic title/description
 * regardless of `searchParams`.
 */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/search">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.search" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

export default async function SearchPage({
  params,
  searchParams,
}: PageProps<"/[locale]/search">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const q = parseQuery(query.q);
  const type = parseType(query.type);
  const page = parsePage(query.page);

  const [t, tType] = await Promise.all([
    getTranslations("Search"),
    getTranslations("Browse"),
  ]);

  // Empty `q` never fetches (FE-11 acceptance: "estado vacío") — the 422 the
  // backend would return for an empty `q` is only reachable defensively,
  // through a malformed/hand-edited URL (see the `status === "invalid"`
  // branch below), not through normal use of `SearchControls`.
  const result = q ? await searchCatalog(q, { type, page }) : null;

  const totalPages =
    result && result.status === "ok" ? Math.max(1, Math.ceil(result.total / result.limit)) : 1;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("heading")}</h1>

      <SearchControls initialQuery={q} initialType={type} />

      {!result ? (
        <p className="text-sm text-muted-foreground">{t("prompt")}</p>
      ) : result.status === "invalid" ? (
        <p role="alert" className="text-sm text-destructive">
          {t("invalidQuery")}
        </p>
      ) : result.status === "rate-limited" ? (
        <RateLimitNotice retryAfterSeconds={result.retryAfterSeconds} />
      ) : result.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty", { query: q })}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {result.results.map((item) => {
              const itemType = toCatalogType(item.item_type);
              return (
                <CatalogCard
                  key={`${item.item_type}-${item.slug}`}
                  title={item.title ?? t("untitled")}
                  posterUrl={item.poster_url}
                  ratingExternal={item.rating_external}
                  typeLabel={itemType ? tType(`heading.${itemType}`) : item.item_type}
                  href={itemType ? `/${itemType}/${item.slug}` : undefined}
                />
              );
            })}
          </div>

          <SearchPagination query={q} type={type} page={result.page} totalPages={totalPages} />
        </>
      )}
    </div>
  );
}
