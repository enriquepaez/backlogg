import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { withSerwist } from "@serwist/turbopack";

const nextConfig: NextConfig = {
  /* config options here */
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
