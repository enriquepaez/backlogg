import { createSerwistRoute } from "@serwist/turbopack";

/**
 * Builds and serves `src/sw.ts` (plus its sourcemap) with esbuild, at
 * `/serwist/sw.js` and `/serwist/sw.js.map`. The `GET` handler sets
 * `Service-Worker-Allowed: /` so a script served from `/serwist/sw.js` can
 * still control the whole origin (see `createSerwistRoute` in
 * `@serwist/turbopack`) — the client registers it with that widened scope in
 * `src/components/service-worker-provider.tsx`.
 *
 * This is the Turbopack-compatible replacement for the classic
 * `public/sw.js` file `@serwist/next`'s webpack plugin used to write to
 * disk: nothing is written to disk here (`write: false` under the hood), the
 * built worker is served directly from this Route Handler.
 */
export const { dynamic, dynamicParams, revalidate, generateStaticParams, GET } =
  createSerwistRoute({
    swSrc: "src/sw.ts",
    // The offline fallback pages aren't picked up by the default static
    // asset globs (`.next/static/**`, `public/**`), so they're precached
    // explicitly. Bump the revision when `[locale]/offline/page.tsx` changes
    // so installed service workers pick up the new content.
    additionalPrecacheEntries: [
      { url: "/en/offline", revision: "1" },
      { url: "/es/offline", revision: "1" },
    ],
  });
