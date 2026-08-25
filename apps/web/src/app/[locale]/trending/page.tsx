import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CatalogCard } from "@/components/catalog-card";
import { TrendingFilters } from "@/components/trending-filters";
import {
  DEFAULT_TRENDING_PERIOD,
  TRENDING_TYPES,
  getTrendingPage,
  trendingItemType,
  type TrendingPeriod,
  type TrendingType,
} from "@/lib/catalog";

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseType(value: RawParam): TrendingType | undefined {
  const raw = firstValue(value);
  return raw && (TRENDING_TYPES as readonly string[]).includes(raw) ? (raw as TrendingType) : undefined;
}

function parsePeriod(value: RawParam): TrendingPeriod {
  const raw = firstValue(value);
  return raw === "day" || raw === "week" ? raw : DEFAULT_TRENDING_PERIOD;
}

/**
 * OG metadata for `/trending` (FE-12). Static regardless of `?type=`/
 * `?period=` — same reasoning as `/genres`' `generateMetadata`.
 */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/trending">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.trending" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

export default async function TrendingPage({
  params,
  searchParams,
}: PageProps<"/[locale]/trending">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const query = await searchParams;
  const type = parseType(query.type);
  const period = parsePeriod(query.period);

  const [t, tBadge, result] = await Promise.all([
    getTranslations("Trending"),
    getTranslations("Home"),
    getTrendingPage({ type, period }),
  ]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("heading")}</h1>

      <TrendingFilters selectedType={type} selectedPeriod={period} />

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {result.results.map((item) => {
            const itemType = trendingItemType(item);
            return (
              <CatalogCard
                key={`${item.item_type}-${item.slug}`}
                title={item.title}
                posterUrl={item.poster_url}
                ratingInternal={item.rating_internal}
                typeLabel={tBadge(`typeBadge.${itemType}`)}
                itemType={itemType}
                href={`/${itemType}/${item.slug}`}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
