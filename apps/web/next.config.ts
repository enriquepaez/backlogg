import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { withSerwist } from "@serwist/turbopack";

const nextConfig: NextConfig = {
  images: {
    // Poster hosts for the catalog (FE-8 home landing is the first feature
    // rendering them via `next/image`). One entry per source adapter — see
    // `docs/external-apis.md` and the `poster_url` builders they document:
    remotePatterns: [
      // TMDB (movies, series, and the trending endpoint — all TMDB-backed).
      { protocol: "https", hostname: "image.tmdb.org", pathname: "/**" },
      // Open Library (books) — `backlogg/books/adapters/open_library.py`.
      { protocol: "https", hostname: "covers.openlibrary.org", pathname: "/**" },
      // IGDB (games) — `backlogg/games/adapters/igdb.py`.
      { protocol: "https", hostname: "images.igdb.com", pathname: "/**" },
    ],
  },
};

// Auto-detects ./src/i18n/request.ts as the request config.
const withNextIntl = createNextIntlPlugin();

// `@serwist/next` (the webpack-based `withSerwistInit`) doesn't support
// Turbopack, the default bundler since Next 16 (see
// `node_modules/next/dist/docs/01-app/02-guides/progressive-web-apps.md`,
// "Offline Support"). `@serwist/turbopack`'s `withSerwist` is the
// Turbopack-compatible replacement: it only adds `esbuild`/`esbuild-wasm` to
// `serverExternalPackages` so the service worker build (triggered by the
// Route Handler at `src/app/serwist/[path]/route.ts`) can run inside the
// Next.js server process. See `src/sw.ts` for the service worker itself.
export default withNextIntl(withSerwist(nextConfig));
