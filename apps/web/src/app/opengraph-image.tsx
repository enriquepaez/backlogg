import { ImageResponse } from "next/og";

/**
 * Generic Open Graph fallback image (FE-45 review fix) — used by
 * `u/[username]/page.tsx` and `u/[username]/library/page.tsx`'s
 * `generateMetadata` when the profile has no `avatar_url`, so a shared link
 * always has *some* preview image instead of none at all.
 *
 * Lives at the root of `app/` (not under `[locale]/`), same placement as
 * `icon.tsx`/`apple-icon.tsx`/`icons/[name]/route.tsx` — this generates a
 * predictable, locale-neutral `/opengraph-image` route that those two pages
 * reference explicitly (see their doc comments), on top of Next.js also
 * auto-wiring it as the OG image for any route that doesn't set its own
 * `openGraph.images` (per
 * `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/01-metadata/opengraph-image.md`).
 *
 * Reuses the same "B" mark visual (`ImageResponse`, no binary brand asset in
 * the repo — see `icon.tsx`'s doc comment) at the standard OG size, `1200x630`.
 */
export const alt = "backlogg";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#18181b",
          color: "#fafafa",
          fontSize: 220,
          fontWeight: 700,
          fontFamily: "sans-serif",
        }}
      >
        B
      </div>
    ),
    { ...size },
  );
}
