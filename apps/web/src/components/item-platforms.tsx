import {
  PLATFORM_COLOR_CLASSES,
  platformFamily,
  type GamePlatform,
} from "@/lib/game-platform-colors";
import { cn } from "@/lib/utils";

export type ItemPlatformsProps = {
  platforms: GamePlatform[];
  heading: string;
  emptyMessage: string;
};

/**
 * Platforms section for the item detail page — game only (FE-64, per the
 * user's explicit request that this occupy the same slot right below the
 * hero, above "Your rating"/"Reviews", that `ItemCredits` occupies for
 * movie/series). Was previously its own badge row inside `ItemHero` (FE-60);
 * moved out into its own section here so the "what goes right after the
 * hero" slot is a single type-dependent choice made by the page (Credits /
 * Platforms / nothing) rather than something embedded inside the hero
 * itself. Same badge styling as before — colored by console-maker family
 * via `platformFamily`/`PLATFORM_COLOR_CLASSES`, neutral `bg-muted` for the
 * unrecognized long tail (see that module's doc comment) — and the same
 * `section`/`h2`/empty-state shape as `ItemCredits`, for visual consistency
 * between the two mutually-exclusive sections that can occupy this slot.
 */
export function ItemPlatforms({ platforms, heading, emptyMessage }: ItemPlatformsProps) {
  const items = platforms ?? [];
  return (
    <section className="mx-auto w-full max-w-6xl px-6 py-8">
      <h2 className="text-xl font-medium">{heading}</h2>
      {items.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          {items.map((platform) => {
            const family = platformFamily(platform);
            return (
              <span
                key={platform.id}
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-xs font-medium",
                  family ? PLATFORM_COLOR_CLASSES[family] : "bg-muted text-muted-foreground",
                )}
              >
                {platform.name}
              </span>
            );
          })}
        </div>
      )}
    </section>
  );
}
