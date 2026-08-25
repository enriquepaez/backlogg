import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { CatalogCard } from "@/components/catalog-card";
import { RecommendationFilters } from "@/components/recommendation-filters";
import { RecommendationsPagination } from "@/components/recommendation-pagination";
import { redirect } from "@/i18n/navigation";
import { getCurrentUser } from "@/lib/api-fetch";
import { isCatalogType, type CatalogType } from "@/lib/catalog-types";
import {
  RECOMMENDATIONS_FALLBACK_REASON,
  getRecommendations,
  recommendationItemType,
} from "@/lib/recommendations";

/** Page size for `/recommendations` — mirrors the backend's own default `limit` (`docs/api.md`). */
const RECOMMENDATIONS_PAGE_SIZE = 20;

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
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

/** OG metadata for `/recommendations` (FE-27), same shape as `/feed`'s `generateMetadata` (FE-23) — private, per-account page, never worth indexing. */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/recommendations">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.recommendations" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    robots: { index: false, follow: false },
    openGraph: { title, description, type: "website" },
  };
}

/**
 * Personalized recommendations (FE-27), `/recommendations`: cross-type
 * `GET /v1/recommendations`, optional `?type=` filter, `page`/`limit`.
 * Protected route — `proxy.ts` already redirects unauthenticated requests
 * away at the edge (`lib/auth/protected-routes.ts` lists `/recommendations`),
 * but that check only looks at cookie PRESENCE, not validity — this page
 * still calls `getCurrentUser()` itself (the real, server-side session
 * check) and redirects to `/login` on `null`, same defense-in-depth as
 * `/feed`'s page (FE-23).
 *
 * `type` is parsed through {@link isCatalogType} before ever reaching
 * `getRecommendations`/the backend — an unrecognized `type` value (typed
 * directly into the URL; the UI itself, `RecommendationFilters`, only ever
 * links to the four valid values) silently falls back to "no filter" rather
 * than forwarding it and surfacing the backend's 422.
 *
 * When the caller has no seeds (no `score >= 4` ratings, nothing
 * `completed`/`want` in their library), every result on the page comes back
 * with the exact same {@link RECOMMENDATIONS_FALLBACK_REASON} reason
 * (`docs/api.md`) — detected here to show an informational banner ("here are
 * some popular picks") ABOVE the grid, on top of each card already showing
 * its own `reason` text. This is a normal, non-error state (a brand new
 * account has no seeds yet), never rendered as `role="alert"`.
 */
export default async function RecommendationsPage({
  params,
  searchParams,
}: PageProps<"/[locale]/recommendations">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const user = await getCurrentUser();
  if (!user) {
    redirect({ href: "/login", locale });
    return;
  }

  const query = await searchParams;
  const type = parseType(query.type);
  const page = parsePage(query.page);

  const [t, tBadge, result] = await Promise.all([
    getTranslations("Recommendations"),
    getTranslations("Home"),
    getRecommendations({ type, page, limit: RECOMMENDATIONS_PAGE_SIZE }),
  ]);

  const isFallback =
    result.ok &&
    result.results.length > 0 &&
    result.results.every((item) => item.reason === RECOMMENDATIONS_FALLBACK_REASON);
  const hasNext = result.ok && result.results.length === result.limit;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("heading")}</h1>

      <RecommendationFilters selectedType={type} />

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <>
          {isFallback ? (
            <p role="status" className="text-sm text-muted-foreground">
              {t("fallback")}
            </p>
          ) : null}

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {result.results.map((item) => {
              const itemType = recommendationItemType(item);
              return (
                <CatalogCard
                  key={`${item.item_type}-${item.slug}`}
                  title={item.title}
                  posterUrl={item.poster_url}
                  ratingInternal={item.rating_internal}
                  typeLabel={tBadge(`typeBadge.${itemType}`)}
                  itemType={itemType}
                  href={`/${itemType}/${item.slug}`}
                  // `item.reason` comes straight from the backend, always in
                  // English (`docs/api.md`: "Because you rated <title>",
                  // "Popular right now") — never run through `t()`, same
                  // reasoning `CatalogCard`'s own doc comment gives for
                  // `title`: catalog/derived content isn't UI chrome.
                  footer={
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                      {item.reason}
                    </p>
                  }
                />
              );
            })}
          </div>

          <RecommendationsPagination type={type} page={result.page} hasNext={hasNext} />
        </>
      )}
    </div>
  );
}
