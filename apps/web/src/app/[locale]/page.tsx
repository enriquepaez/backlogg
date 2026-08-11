import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CatalogCard } from "@/components/catalog-card";
import { CatalogSection } from "@/components/catalog-section";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import {
  CATALOG_TYPES,
  getAllFeatured,
  getTrending,
  type CatalogType,
  type TrendingItem,
} from "@/lib/catalog";

/**
 * OG metadata for the home page. Reuses the same `Metadata.home` strings the
 * root `[locale]/layout.tsx` already sets as `title`/`description` (so this
 * doesn't fork the copy) and adds `openGraph` on top — Next merges a page's
 * `generateMetadata` over its parent layout's rather than requiring the page
 * to redeclare everything (see `node_modules/next/dist/docs/01-app/03-api-reference/04-functions/generate-metadata.md`).
 */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Metadata.home" });
  const title = t("title");
  const description = t("description");

  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
  };
}

/** Maps the trending endpoint's uppercase `item_type` to the lowercase `CatalogType` vocabulary used elsewhere (routes, `Home.typeBadge`). */
function trendingItemType(item: TrendingItem): Extract<CatalogType, "movie" | "series"> {
  return item.item_type === "MOVIE" ? "movie" : "series";
}

export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Home");

  const [trending, featured] = await Promise.all([
    getTrending(),
    getAllFeatured(),
  ]);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-16 px-6 py-16">
      <section className="flex flex-col items-start gap-6 text-left">
        <h1 className="max-w-2xl text-4xl font-semibold leading-tight tracking-tight">
          {t("title")}
        </h1>
        <p className="max-w-xl text-lg leading-8 text-muted-foreground">
          {t("description")}
        </p>
        <Button asChild>
          <Link href="/search">{t("searchCta")}</Link>
        </Button>
      </section>

      <CatalogSection
        heading={t("trendingTitle")}
        isEmpty={trending.length === 0}
        emptyMessage={t("trendingEmpty")}
        viewAllHref="/trending"
        viewAllLabel={t("trendingViewAll")}
      >
        {trending.map((item) => {
          const type = trendingItemType(item);
          return (
            <CatalogCard
              key={`${item.item_type}-${item.slug}`}
              title={item.title}
              posterUrl={item.poster_url}
              ratingExternal={item.rating_external}
              typeLabel={t(`typeBadge.${type}`)}
              href={`/${type}/${item.slug}`}
            />
          );
        })}
      </CatalogSection>

      {CATALOG_TYPES.map((type) => {
        const items = featured[type];
        return (
          <CatalogSection
            key={type}
            heading={t(`types.${type}`)}
            isEmpty={items.length === 0}
            emptyMessage={t("featuredEmpty")}
            viewAllHref={`/browse/${type}`}
            viewAllLabel={t("viewAll", { type: t(`types.${type}`) })}
          >
            {items.map((item) => (
              <CatalogCard
                key={item.slug}
                title={item.title}
                posterUrl={item.poster_url}
                ratingExternal={item.rating_external}
                href={`/${type}/${item.slug}`}
              />
            ))}
          </CatalogSection>
        );
      })}
    </div>
  );
}
