/// <reference lib="webworker" />

import { defaultCache } from "@serwist/turbopack/worker";
import { Serwist } from "serwist";
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";

/**
 * Service worker source for the PWA app shell (FE-6).
 *
 * Bundled at request/build time by esbuild via the Route Handler at
 * `src/app/serwist/[path]/route.ts` (`createSerwistRoute` from
 * `@serwist/turbopack` — the Turbopack-compatible replacement for the
 * classic webpack `InjectManifest` plugin used by `@serwist/next`; see
 * `next.config.ts`). This file is intentionally excluded from the app's
 * main `tsconfig.json` (see that file) because it needs the `webworker` lib,
 * which conflicts with the `dom` lib the rest of the app (a browser +
 * Node.js codebase) is type-checked against.
 *
 * `self.__SW_MANIFEST` below is not a real runtime global — esbuild's
 * `define` step (driven by `createSerwistRoute`) textually replaces this
 * exact expression with the precache manifest as a JSON literal, so it must
 * stay written like this (no destructuring, no aliasing).
 */
declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

/**
 * Locale-prefixed offline fallback pages (`src/app/[locale]/offline/page.tsx`).
 * Precached explicitly via `additionalPrecacheEntries` in
 * `src/app/serwist/[path]/route.ts` — they aren't reachable by the static
 * asset globs (those only cover `.next/static/**` and `public/**`).
 */
const OFFLINE_URL = { en: "/en/offline", es: "/es/offline" } as const;

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  // `defaultCache` is Serwist's Next.js-aware runtime caching list:
  // NetworkFirst (with a short timeout) for documents, RSC payloads and
  // `/api/*` calls — so SSR/ISR content and the BFF are never served stale —
  // and CacheFirst/StaleWhileRevalidate only for fonts/images/JS/CSS. In
  // development it degrades to NetworkOnly for everything, so the SW never
  // interferes with HMR. See
  // `node_modules/@serwist/turbopack/dist/index.worker.mjs`.
  runtimeCaching: defaultCache,
  fallbacks: {
    // Minimal offline app shell: only kicks in when a *document* (page
    // navigation) request fails and nothing else answers it from cache.
    // Non-navigation requests (JS/CSS/images/API calls) are untouched, so a
    // failed data fetch never silently renders the offline page's markup.
    entries: [
      {
        url: OFFLINE_URL.es,
        matcher: ({ request }) =>
          request.destination === "document" &&
          new URL(request.url).pathname.startsWith("/es"),
      },
      {
        url: OFFLINE_URL.en,
        matcher: ({ request }) => request.destination === "document",
      },
    ],
  },
});

serwist.addEventListeners();
