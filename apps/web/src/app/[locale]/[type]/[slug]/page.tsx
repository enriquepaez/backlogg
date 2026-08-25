import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { ItemCredits, type ItemCredit } from "@/components/item-credits";
import { ItemHero, type ItemMetadataField } from "@/components/item-hero";
import { ItemReviews } from "@/components/item-reviews";
import { ItemSimilar } from "@/components/item-similar";
import { RatingWidget } from "@/components/rating-widget";
import { env } from "@/lib/env";
import {
  getItemDetail,
  getSimilarItems,
  isCatalogType,
  type BookDetail,
  type CatalogType,
  type GameDetail,
  type ItemDetail,
  type MovieDetail,
  type SeriesDetail,
} from "@/lib/catalog";

/**
 * schema.org `@type` per catalog type (FE-53 acceptance criteria) —
 * movie/series/book/game map 1:1 onto Movie/TVSeries/Book/VideoGame, all
 * `CreativeWork` subtypes, which is what lets {@link buildJsonLd} use the
 * single `datePublished`/`aggregateRating` shape below for all four instead
 * of branching per schema.org type as well as per {@link CatalogType}.
 */
const SCHEMA_TYPE_BY_CATALOG_TYPE: Record<CatalogType, string> = {
  movie: "Movie",
  series: "TVSeries",
  book: "Book",
  game: "VideoGame",
};

/**
 * `user_ratings.score` range (`ck_user_ratings_score_range`, `docs/schema.md`)
 * — the scale `rating_internal` (its per-item average) lives on. Also
 * schema.org's own implicit default for `AggregateRating` when
 * `bestRating`/`worstRating` are omitted, but set explicitly below so the
 * JSON-LD doesn't silently break if that default ever changes upstream.
 */
const RATING_INTERNAL_MIN = 1;
const RATING_INTERNAL_MAX = 5;

/** Autocanonical path for one item detail page — no query params, ever (FE-53). */
function itemPath(locale: string, type: CatalogType, slug: string): string {
  return `/${locale}/${type}/${slug}`;
}

type ItemDetailTranslator = Awaited<ReturnType<typeof getTranslations<"ItemDetail">>>;

/**
 * Type-specific metadata rows (release date, runtime, seasons, platforms,
 * ...) for `ItemHero`'s `fields` prop. `item`'s shape is guaranteed to
 * correspond to `type` — both always come from the very same
 * `getItemDetail(type, slug)` call below — but `ItemDetail` itself is a
 * union (the four `*Out` response shapes genuinely differ), so each branch
 * narrows with a plain `as` cast rather than threading a generic through the
 * whole page. Only pushes a field when the underlying value is present —
 * external data is frequently partial (e.g. Open Library rarely has
 * `original_language`).
 */
function buildFields(
  type: CatalogType,
  item: ItemDetail,
  t: ItemDetailTranslator,
): ItemMetadataField[] {
  const fields: ItemMetadataField[] = [];

  switch (type) {
    case "movie": {
      const movie = item as MovieDetail;
      if (movie.release_date) {
        fields.push({ label: t("fields.releaseDate"), value: movie.release_date });
      }
      if (movie.runtime) {
        fields.push({
          label: t("fields.runtime"),
          value: t("fields.runtimeValue", { minutes: movie.runtime }),
        });
      }
      if (movie.status) {
        fields.push({ label: t("fields.status"), value: movie.status });
      }
      if (movie.original_language) {
        fields.push({ label: t("fields.originalLanguage"), value: movie.original_language });
      }
      break;
    }
    case "series": {
      const series = item as SeriesDetail;
      if (series.first_air_date) {
        fields.push({ label: t("fields.firstAirDate"), value: series.first_air_date });
      }
      if (series.last_air_date) {
        fields.push({ label: t("fields.lastAirDate"), value: series.last_air_date });
      }
      if (series.number_of_seasons) {
        fields.push({ label: t("fields.seasons"), value: String(series.number_of_seasons) });
      }
      if (series.number_of_episodes) {
        fields.push({ label: t("fields.episodes"), value: String(series.number_of_episodes) });
      }
      if (series.status) {
        fields.push({ label: t("fields.status"), value: series.status });
      }
      if (series.original_language) {
        fields.push({ label: t("fields.originalLanguage"), value: series.original_language });
      }
      break;
    }
    case "book": {
      const book = item as BookDetail;
      if (book.first_publish_date) {
        fields.push({ label: t("fields.firstPublishDate"), value: book.first_publish_date });
      }
      if (book.original_language) {
        fields.push({ label: t("fields.originalLanguage"), value: book.original_language });
      }
      break;
    }
    case "game": {
      const game = item as GameDetail;
      if (game.release_date) {
        fields.push({ label: t("fields.releaseDate"), value: game.release_date });
      }
      if (game.game_type) {
        fields.push({ label: t("fields.gameType"), value: game.game_type });
      }
      if (game.platforms && game.platforms.length > 0) {
        fields.push({
          label: t("fields.platforms"),
          value: game.platforms.map((platform) => platform.name).join(", "),
        });
      }
      if (game.original_language) {
        fields.push({ label: t("fields.originalLanguage"), value: game.original_language });
      }
      break;
    }
  }

  return fields;
}

/**
 * schema.org `datePublished` per catalog type (FE-53) — the same
 * release-date field {@link buildFields} surfaces first for each type
 * (`release_date`/`first_air_date`/`first_publish_date`/`release_date`), via
 * the same per-type `as` narrowing since `ItemDetail` is a union. `null`
 * when the underlying value is absent — external data is frequently partial,
 * same reasoning as {@link buildFields}.
 */
function itemDatePublished(type: CatalogType, item: ItemDetail): string | null {
  switch (type) {
    case "movie":
      return (item as MovieDetail).release_date;
    case "series":
      return (item as SeriesDetail).first_air_date;
    case "book":
      return (item as BookDetail).first_publish_date;
    case "game":
      return (item as GameDetail).release_date;
  }
}

/**
 * JSON-LD payload for the item detail page (FE-53) — rendered as a
 * `<script type="application/ld+json">` by the page component below, per
 * Next's own documented pattern (`node_modules/next/dist/docs/.../json-ld.md`).
 * `aggregateRating` is only included once there is at least one visible
 * rating (`rating_count_internal > 0`): Google's structured data guidelines
 * reject a `ratingCount` of 0, and `rating_internal` itself is `null` until
 * then anyway (`docs/schema.md`).
 */
function buildJsonLd(type: CatalogType, item: ItemDetail, url: string): Record<string, unknown> {
  const jsonLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": SCHEMA_TYPE_BY_CATALOG_TYPE[type],
    name: item.title,
    url,
  };

  if (item.poster_url) {
    jsonLd.image = item.poster_url;
  }

  const datePublished = itemDatePublished(type, item);
  if (datePublished) {
    jsonLd.datePublished = datePublished;
  }

  if (item.rating_internal !== null && item.rating_count_internal > 0) {
    jsonLd.aggregateRating = {
      "@type": "AggregateRating",
      ratingValue: item.rating_internal,
      ratingCount: item.rating_count_internal,
      bestRating: RATING_INTERNAL_MAX,
      worstRating: RATING_INTERNAL_MIN,
    };
  }

  return jsonLd;
}

/**
 * `credits[]` exists on all four detail shapes (`docs/api.md`) — movies/
 * series/games expose cast & crew, books expose the author(s) as a credit
 * with `role: "AUTHOR"`. `ItemCredits`' heading/empty copy is a single
 * type-agnostic "Credits" label (`ItemDetail.credits` in
 * `messages/{en,es}.json`) rather than per-type wording, since a single
 * author doesn't fit a "Cast & crew" framing — same simple, presentational
 * spirit as the rest of this component (see its own doc comment).
 *
 * Defensive `?? []`: the generated `ItemDetail` type says `credits` is
 * always an array, but an empty `credits: []` from the backend has been
 * observed reaching this page as `undefined` for at least one real item
 * (book-detail crash bugfix — see `progress/history.md`). No section of
 * this page should be able to take down the whole render over a
 * missing/malformed array field, same spirit as {@link getSimilarItems}
 * (already degrades to `[]` on failure) and {@link buildFields}' `platforms`
 * handling below.
 */
function getCredits(item: ItemDetail): ItemCredit[] {
  return item.credits ?? [];
}

/** `backdrop_url` only exists on `MovieOut`/`SeriesOut`/`GameOut` — `BookOut` has none (`docs/api.md`). */
function getBackdropUrl(type: CatalogType, item: ItemDetail): string | null {
  if (type === "book") {
    return null;
  }
  return (item as MovieDetail | SeriesDetail | GameDetail).backdrop_url;
}

/**
 * OG metadata for the item detail page (FE-10). Returns `{}` (falls back to
 * the root layout's `Metadata.home` title/description) for an invalid
 * `type`, a genuine 404, or a transient fetch failure — the page itself
 * handles those cases distinctly (`notFound()` vs an inline error state, see
 * `getItemDetail`'s doc comment in `src/lib/catalog.ts`); metadata just
 * degrades quietly rather than duplicating that branching.
 *
 * Calls {@link getItemDetail} with the exact same arguments (and `next`
 * cache options) the page component below uses — Next dedupes identical
 * `fetch()` calls within one render pass, so this doesn't double the network
 * request per page view.
 */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/[type]/[slug]">): Promise<Metadata> {
  const { locale, type: rawType, slug } = await params;
  if (!isCatalogType(rawType)) {
    return {};
  }

  const result = await getItemDetail(rawType, slug);
  if (result.status !== "ok") {
    return {};
  }

  const item = result.item;
  const tm = await getTranslations({ locale, namespace: "Metadata.item" });
  const title = tm("title", { title: item.title });
  const description = item.overview ?? tm("descriptionFallback", { title: item.title });

  return {
    title,
    description,
    alternates: { canonical: itemPath(locale, rawType, slug) },
    openGraph: {
      title,
      description,
      type: "website",
      images: item.poster_url ? [item.poster_url] : undefined,
    },
  };
}

export default async function ItemDetailPage({
  params,
}: PageProps<"/[locale]/[type]/[slug]">) {
  const { locale, type: rawType, slug } = await params;
  setRequestLocale(locale);

  if (!isCatalogType(rawType)) {
    notFound();
  }
  const type = rawType;

  const [result, similar, t] = await Promise.all([
    getItemDetail(type, slug),
    getSimilarItems(type, slug),
    getTranslations("ItemDetail"),
  ]);

  // Only a backend-confirmed 404 is a real "not found" — see
  // `ItemDetailResult`'s doc comment in `src/lib/catalog.ts` for why a
  // transient failure (below) must not go through `notFound()` too.
  if (result.status === "not-found") {
    notFound();
  }

  if (result.status === "error") {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-16">
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      </div>
    );
  }

  const item = result.item;
  const jsonLd = buildJsonLd(type, item, `${env.SITE_URL}${itemPath(locale, type, slug)}`);

  return (
    <div className="flex flex-col">
      {/*
        Structured data (FE-53): a plain `<script>`, not `next/script`, per
        Next's own guidance — JSON-LD is data, not executable code
        (`node_modules/next/dist/docs/.../json-ld.md`). `JSON.stringify` +
        the `<` escape (same doc) is applied even though `jsonLd`'s strings
        come from catalog sync, not user input: an external title/overview
        containing a literal `<` would otherwise close the script tag early.
      */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
      />

      <ItemHero
        title={item.title}
        originalTitle={item.original_title}
        overview={item.overview}
        posterUrl={item.poster_url}
        backdropUrl={getBackdropUrl(type, item)}
        ratingInternal={item.rating_internal}
        ratingCountInternal={item.rating_count_internal}
        genres={(item.genres ?? []).map((genre) => genre.name)}
        fields={buildFields(type, item, t)}
        viewerStatus={item.viewer_status}
        type={type}
        slug={slug}
        originalTitleLabel={t("originalTitleLabel")}
        genresLabel={t("genresLabel")}
        ratingInternalLabel={t("ratingInternalLabel")}
        noRatingsLabel={t("noRatings")}
      />

      <RatingWidget
        type={type}
        slug={slug}
        initialRatingInternal={item.rating_internal}
        initialRatingCountInternal={item.rating_count_internal}
      />

      <ItemReviews type={type} slug={slug} />

      <ItemCredits
        credits={getCredits(item)}
        heading={t("credits.heading")}
        emptyMessage={t("credits.empty")}
      />

      <ItemSimilar
        type={type}
        items={similar}
        heading={t("similar.heading")}
        emptyMessage={t("similar.empty")}
      />
    </div>
  );
}
