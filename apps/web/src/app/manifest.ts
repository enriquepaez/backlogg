import type { MetadataRoute } from "next";

/**
 * Web app manifest (FE-6). Lives at the root of `app/` — not under
 * `[locale]/` — per
 * `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/01-metadata/manifest.md`
 * ("Add ... a `manifest.(json|webmanifest)` file ... in the **root** of the
 * `app` directory"). Next auto-injects the `<link rel="manifest">` tag on
 * every route, so no wiring is needed in `[locale]/layout.tsx`.
 *
 * Intentionally locale-neutral (English fallback) rather than reading
 * `next-intl` here: this file is cached/prerendered once for the whole app,
 * and making it read the request locale would opt it out of that caching
 * (see the manifest doc: "manifest.js ... is cached by default unless it
 * uses a Request-time API"). The rest of the UI is still fully
 * i18n-covered (FE-3b).
 *
 * `icons` references `icon.tsx`/`apple-icon.tsx` (favicon + Apple touch
 * icon, wired automatically into `<head>`) plus the dedicated
 * `icons/[name]/route.tsx` sizes below, which Lighthouse's installability
 * audit requires (at least one icon >= 192x192 and one >= 512x512).
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "backlogg",
    short_name: "backlogg",
    description:
      "Track and rate the movies, series, books and games you love.",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#18181b",
    icons: [
      {
        src: "/icons/icon-192",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512-maskable",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
