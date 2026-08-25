import { ImageOff, Star } from "lucide-react";
import Image from "next/image";

import { ViewerStatusSlot } from "@/components/viewer-status-slot";
import type { CatalogType } from "@/lib/catalog-types";
import {
  PLATFORM_COLOR_CLASSES,
  platformFamily,
  type GamePlatform,
} from "@/lib/game-platform-colors";
import { cn } from "@/lib/utils";

export type ItemMetadataField = {
  label: string;
  value: string;
};

export type ItemHeroProps = {
  /** Item title. Catalog content is never translated (see `apps/web/AGENTS.md` / i18n note). */
  title: string;
  /** Omitted from the metadata row when equal to `title` (most items don't have a distinct original title). */
  originalTitle: string | null;
  overview: string | null;
  posterUrl: string | null;
  /** `null` for books (`BookOut` has no `backdrop_url`, see `docs/api.md`). */
  backdropUrl: string | null;
  ratingInternal: number | null;
  ratingCountInternal: number;
  /** Genre names (already resolved from `GenreOut`/`BookGenreOut`/etc by the caller). */
  genres: string[];
  /**
   * `GameOut.platforms` (FE-60) — own badge row, colored by console-maker
   * family via `platformFamily`/`PLATFORM_COLOR_CLASSES`
   * (`game-platform-colors.ts`), same visual slot pattern as {@link genres}
   * right above it but with a brand-color signal instead of a flat neutral
   * pill. `undefined`/empty for movies/series/books — this row only renders
   * when non-empty, same guard as {@link genres}. Kept as its own prop
   * rather than folded into {@link fields} (where `GameOut.platforms` lived
   * before FE-60): `fields` is a plain label/value `dl` with no room for a
   * per-item color, and platforms — unlike every other field there — needed
   * one (FE-60 acceptance).
   */
  platforms?: GamePlatform[];
  /** aria-label for the {@link platforms} row, same convention as `genresLabel` below. */
  platformsLabel: string;
  /** Type-specific metadata (release date, runtime, seasons, ...), built by the page per {@link CatalogType}. */
  fields: ItemMetadataField[];
  /** `MovieOut.viewer_status` (etc) — see `ViewerStatusSlot`. */
  viewerStatus: string | null | undefined;
  /** Forwarded to `ViewerStatusSlot`, which needs them for its own `GET/PUT/DELETE /api/{type}/{slug}/library` calls (FE-20). */
  type: CatalogType;
  slug: string;
  originalTitleLabel: string;
  genresLabel: string;
  ratingInternalLabel: string;
  noRatingsLabel: string;
};

/**
 * The community's own rating badge (`rating_internal`), or the "no ratings
 * yet" fallback — `rating_internal` is `null` until at least one user has
 * rated the item (`docs/schema.md`), which is expected to be common early
 * on since ratings/reviews (FE-18) haven't shipped yet. `rating_external`
 * (TMDB/Open Library/IGDB) is never shown to end users (FE-59/backend
 * `rating_display_internal_only`) — kept generic (label/value/count props)
 * in case another internal-only rating badge needs the same shape later.
 */
function RatingBadge({
  label,
  value,
  count,
  noRatingsLabel,
}: {
  label: string;
  value: number | null;
  count: number | null;
  noRatingsLabel: string;
}) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg bg-muted px-2.5 py-1.5 text-sm">
      <Star aria-hidden className="size-4 fill-current text-yellow-500" />
      <span className="sr-only">{label}</span>
      {value != null ? (
        <span className="font-medium">
          {value.toFixed(1)}
          {count != null && count > 0 ? (
            <span className="ml-1 text-muted-foreground">({count})</span>
          ) : null}
        </span>
      ) : (
        <span className="text-muted-foreground">{noRatingsLabel}</span>
      )}
    </div>
  );
}

/**
 * Item detail page's hero section (FE-10): backdrop, poster, title, ratings,
 * overview, genres, type-specific metadata fields, and the `viewer_status`
 * extension point. Purely presentational — like `CatalogCard`/`CatalogSection`
 * (FE-8/FE-9), it takes plain, already-translated label strings as props
 * instead of calling `useTranslations` itself: the page (a Server Component)
 * resolves `ItemDetail`'s messages once via `getTranslations` and threads
 * them down, so this component doesn't need an opinion on whether it's
 * rendered in a server or client context.
 */
export function ItemHero({
  title,
  originalTitle,
  overview,
  posterUrl,
  backdropUrl,
  ratingInternal,
  ratingCountInternal,
  genres,
  platforms,
  platformsLabel,
  fields,
  viewerStatus,
  type,
  slug,
  originalTitleLabel,
  genresLabel,
  ratingInternalLabel,
  noRatingsLabel,
}: ItemHeroProps) {
  return (
    <section className="relative">
      {backdropUrl ? (
        <div className="absolute inset-0 -z-10 overflow-hidden">
          <Image
            src={backdropUrl}
            alt=""
            aria-hidden
            fill
            sizes="100vw"
            className="object-cover opacity-20"
            priority
          />
          <div className="absolute inset-0 bg-gradient-to-b from-background/40 to-background" />
        </div>
      ) : null}

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-16 sm:flex-row">
        <div className="relative aspect-2/3 w-48 shrink-0 overflow-hidden rounded-xl bg-muted sm:w-64">
          {posterUrl ? (
            <Image
              src={posterUrl}
              alt={title}
              fill
              sizes="(max-width: 640px) 192px, 256px"
              className="object-cover"
              priority
            />
          ) : (
            <div
              role="img"
              aria-label={title}
              className="flex h-full w-full items-center justify-center text-muted-foreground"
            >
              <ImageOff aria-hidden className="size-10" />
            </div>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
            {originalTitle && originalTitle !== title ? (
              <p className="mt-1 text-sm text-muted-foreground">
                {originalTitleLabel}: {originalTitle}
              </p>
            ) : null}
          </div>

          {genres.length > 0 ? (
            <div aria-label={genresLabel} className="flex flex-wrap gap-2">
              {genres.map((genre) => (
                <span
                  key={genre}
                  className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground"
                >
                  {genre}
                </span>
              ))}
            </div>
          ) : null}

          {platforms && platforms.length > 0 ? (
            <div aria-label={platformsLabel} className="flex flex-wrap gap-2">
              {platforms.map((platform) => {
                const family = platformFamily(platform);
                return (
                  <span
                    key={platform.id}
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-xs font-medium",
                      family
                        ? PLATFORM_COLOR_CLASSES[family]
                        : "bg-muted text-muted-foreground",
                    )}
                  >
                    {platform.name}
                  </span>
                );
              })}
            </div>
          ) : null}

          <div className="flex flex-wrap gap-2">
            <RatingBadge
              label={ratingInternalLabel}
              value={ratingInternal}
              count={ratingCountInternal}
              noRatingsLabel={noRatingsLabel}
            />
          </div>

          {overview ? (
            <p className="max-w-2xl whitespace-pre-line text-base leading-7 text-muted-foreground">
              {overview}
            </p>
          ) : null}

          {fields.length > 0 ? (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
              {fields.map((field) => (
                <div key={field.label}>
                  <dt className="text-muted-foreground">{field.label}</dt>
                  <dd className="font-medium">{field.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}

          <ViewerStatusSlot status={viewerStatus} type={type} slug={slug} />
        </div>
      </div>
    </section>
  );
}
