import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";

import { ItemCredits, type ItemCredit } from "@/components/item-credits";
import { ItemHero, type ItemMetadataField } from "@/components/item-hero";
import { ItemSimilar } from "@/components/item-similar";
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

  return (
    <div className="flex flex-col">
      <ItemHero
        title={item.title}
        originalTitle={item.original_title}
        overview={item.overview}
        posterUrl={item.poster_url}
        backdropUrl={getBackdropUrl(type, item)}
        ratingExternal={item.rating_external}
        ratingCountExternal={item.rating_count_external}
        ratingInternal={item.rating_internal}
        ratingCountInternal={item.rating_count_internal}
        genres={(item.genres ?? []).map((genre) => genre.name)}
        fields={buildFields(type, item, t)}
        viewerStatus={item.viewer_status}
        originalTitleLabel={t("originalTitleLabel")}
        genresLabel={t("genresLabel")}
        ratingExternalLabel={t("ratingExternalLabel")}
        ratingInternalLabel={t("ratingInternalLabel")}
        noRatingsLabel={t("noRatings")}
      />

      <ItemCredits
        credits={getCredits(item)}
        heading={t("credits.heading")}
        emptyMessage={t("credits.empty")}
      />

      {type === "movie" || type === "series" ? (
        <ItemSimilar
          type={type}
          items={similar}
          heading={t("similar.heading")}
          emptyMessage={t("similar.empty")}
        />
      ) : null}
    </div>
  );
}
