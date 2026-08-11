import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { GenreFilters } from "@/components/genre-filters";
import { GenreSections } from "@/components/genre-sections";
import { CATALOG_TYPES, getGenrePage, isCatalogType, type CatalogType } from "@/lib/catalog";

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseType(value: RawParam): CatalogType | undefined {
  const raw = firstValue(value);
  return raw && isCatalogType(raw) ? raw : undefined;
}

/**
 * OG metadata for `/genres` (FE-12). Static regardless of `?type=` — like
 * `/search`'s `generateMetadata` (FE-11), the filter is a view of the same
 * page, not a distinct content dimension worth indexing per-value.
 */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/genres">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.genres" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

export default async function GenresPage({
  params,
  searchParams,
}: PageProps<"/[locale]/genres">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const type = parseType(query.type);

  const [t, tBrowse, result] = await Promise.all([
    getTranslations("Genres"),
    getTranslations("Browse"),
    getGenrePage(type),
  ]);

  const typeLabels = Object.fromEntries(
    CATALOG_TYPES.map((catalogType) => [catalogType, tBrowse(`heading.${catalogType}`)]),
  ) as Record<CatalogType, string>;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">{t("heading")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
      </div>

      <GenreFilters selectedType={type} />

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.genres.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <GenreSections genres={result.genres} selectedType={type} typeLabels={typeLabels} />
      )}
    </div>
  );
}
