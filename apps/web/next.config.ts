import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { withSerwist } from "@serwist/turbopack";

const nextConfig: NextConfig = {
  // `next dev`'s default same-origin protection only trusts `localhost`, but
  // Playwright's e2e suite (`playwright.config.ts`) navigates against
  // `127.0.0.1` (needed so the Next server and `e2e/mock-backend.mjs` — see
  // that file's doc comment — can bind to distinct, predictable loopback
  // ports without touching `/etc/hosts`). Without this, every dev-mode JS
  // chunk request from a `127.0.0.1`-loaded page 403s and the client never
  // hydrates — invisible to the pre-FE-14 e2e specs (none needed
  // interactivity), surfaced by `e2e/session-ux.spec.ts`'s dropdown-menu
  // clicks. Dev-only (Next enforces `allowedDevOrigins` in `next dev` only).
  allowedDevOrigins: ["127.0.0.1"],
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
