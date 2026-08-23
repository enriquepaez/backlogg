import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { withSerwist } from "@serwist/turbopack";

// Avatar storage host (FE-49) — unlike the three catalog poster hosts below
// (fixed at build time, one per source adapter), this one varies by
// environment: MinIO in dev (`http://localhost:9000/avatars`, explicit
// port) vs Supabase Storage in prod (`https://<project-ref>.supabase.co/...`,
// no port), mirroring the backend's own R2_PUBLIC_BASE_URL
// (`backlogg/core/config.py`) since `avatar_url` in API responses is already
// that base + object key. AVATAR_PUBLIC_BASE_URL (`.env.example`) is read
// directly from `process.env` here — this file runs in Node at build/dev
// time, not through `src/lib/env.ts`'s server-only client-safety guard —
// and parsed with `URL` so `port` is derived correctly instead of hand-
// rolled with a regex: `remotePatterns` needs `hostname` and `port` as
// separate fields, and naively splitting on ":" would also break for IPv6
// hosts. Left unset in an environment (rather than `required()`-style
// throwing), the avatar host is simply omitted from `remotePatterns` —
// avatars fall back to `<img>` call sites elsewhere in the app (out of this
// feature's scope) rather than failing the build.
const avatarPublicBaseUrl = process.env.AVATAR_PUBLIC_BASE_URL;
const avatarRemotePattern = avatarPublicBaseUrl
  ? (() => {
      const { protocol, hostname, port, pathname } = new URL(avatarPublicBaseUrl);
      return {
        protocol: protocol.replace(":", "") as "http" | "https",
        hostname,
        port,
        pathname: `${pathname}/**`,
      };
    })()
  : null;

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
      // User avatar storage (FE-49) — see `avatarRemotePattern` above for why
      // this one is derived from an env var instead of hardcoded.
      ...(avatarRemotePattern ? [avatarRemotePattern] : []),
    ],
    // Next.js 16 added an SSRF guard (`node_modules/next/dist/docs/01-app/
    // 02-guides/upgrading/version-16.md`, "A new security restriction blocks
    // local IP optimization by default") that rejects `/_next/image` fetches
    // to any hostname resolving to a local/private IP — `localhost` included
    // — even when that host IS listed in `remotePatterns` above (both cases
    // throw the exact same `"url" parameter is not allowed` error, which is
    // why this looked like a `remotePatterns` bug at first). MinIO in dev
    // (`avatarPublicBaseUrl`, see above) is exactly that: a private, locally-
    // hosted image origin we already trust and explicitly opted into via
    // `AVATAR_PUBLIC_BASE_URL` — so it's the case the Next docs mean by
    // "Only for private networks". Scoped to only when the avatar host
    // itself is local, so this stays `false` (the safe default) in prod,
    // where `AVATAR_PUBLIC_BASE_URL` points at a real public Supabase
    // Storage domain, not a local IP.
    dangerouslyAllowLocalIP:
      avatarRemotePattern?.hostname === "localhost" || avatarRemotePattern?.hostname === "127.0.0.1",
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
