import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { BrowseFilters } from "@/components/browse-filters";
import { BrowsePagination } from "@/components/browse-pagination";
import { CatalogCard } from "@/components/catalog-card";
import {
  CATALOG_SORTS,
  DEFAULT_CATALOG_SORT,
  getGenres,
  isCatalogType,
  listCatalog,
  type CatalogSort,
} from "@/lib/catalog";

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseSort(value: RawParam): CatalogSort {
  const raw = firstValue(value);
  return raw && (CATALOG_SORTS as readonly string[]).includes(raw)
    ? (raw as CatalogSort)
    : DEFAULT_CATALOG_SORT;
}

function parsePage(value: RawParam): number {
  const raw = firstValue(value);
  const parsed = raw ? Number.parseInt(raw, 10) : 1;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

function parseGenre(value: RawParam): string | undefined {
  const raw = firstValue(value);
  return raw && raw.length > 0 ? raw : undefined;
}

/**
 * OG metadata for `/browse/{type}` (FE-9), same shape as the home page's
 * `generateMetadata` (FE-8): reads the localized type label from `Browse`
 * and interpolates it into `Metadata.browse`'s title/description templates.
 * Deliberately ignores `searchParams` (genre/sort/page) — the metadata
 * describes the type-level list, not one particular filtered/paginated
 * view of it.
 */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/browse/[type]">): Promise<Metadata> {
  const { locale, type } = await params;
  if (!isCatalogType(type)) {
    return {};
  }

  const [t, tm] = await Promise.all([
    getTranslations({ locale, namespace: "Browse" }),
    getTranslations({ locale, namespace: "Metadata.browse" }),
  ]);
  const typeLabel = t(`heading.${type}`);
  const title = tm("title", { type: typeLabel });
  const description = tm("description", { type: typeLabel });

  return {
    title,
    description,
    // Autocanonical (FE-53), deliberately WITHOUT `genre`/`sort`/`page` —
    // same "describes the type-level list" reasoning as ignoring
    // `searchParams` above: every filtered/sorted/paginated view of
    // `/browse/{type}` canonicalizes to this one URL rather than being
    // indexed as its own distinct page.
    alternates: { canonical: `/${locale}/browse/${type}` },
    openGraph: { title, description, type: "website" },
  };
}

export default async function BrowsePage({
  params,
  searchParams,
}: PageProps<"/[locale]/browse/[type]">) {
  const { locale, type: rawType } = await params;
  setRequestLocale(locale);

  if (!isCatalogType(rawType)) {
    notFound();
  }
  const type = rawType;

  const query = await searchParams;
  const genre = parseGenre(query.genre);
  const sort = parseSort(query.sort);
  const page = parsePage(query.page);

  const [t, tBadge] = await Promise.all([
    getTranslations("Browse"),
    // FE-57: the type badge's singular label ("Movie") lives in `Home.
    // typeBadge` — reused here (rather than `Browse.heading`, which holds
    // the plural page heading, "Movies") so the badge text matches every
    // other grid's type badge exactly.
    getTranslations("Home"),
  ]);

  const [result, genres] = await Promise.all([
    listCatalog(type, { genre, sort, page }),
    getGenres(type),
  ]);

  const totalPages = result.ok
    ? Math.max(1, Math.ceil(result.total / result.limit))
    : 1;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">
        {t(`heading.${type}`)}
      </h1>

      <BrowseFilters
        type={type}
        genres={genres}
        selectedGenre={genre}
        selectedSort={sort}
      />

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {result.items.map((item) => (
              <CatalogCard
                key={item.slug}
                title={item.title}
                posterUrl={item.poster_url}
                ratingInternal={item.rating_internal}
                typeLabel={tBadge(`typeBadge.${type}`)}
                itemType={type}
                href={`/${type}/${item.slug}`}
              />
            ))}
          </div>

          <BrowsePagination
            type={type}
            page={result.page}
            totalPages={totalPages}
            genre={genre}
            sort={sort}
          />
        </>
      )}
    </div>
  );
}
