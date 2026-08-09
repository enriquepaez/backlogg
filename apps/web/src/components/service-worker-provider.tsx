"use client";

import type { ReactNode } from "react";
import { SerwistProvider } from "@serwist/turbopack/react";

/**
 * Registers the service worker built by `src/app/serwist/[path]/route.ts`
 * (see `src/sw.ts`) and exposes it to the tree via `@serwist/turbopack`'s
 * `useSerwist` hook, if a descendant ever needs it. `Service-Worker-Allowed:
 * /` (set by that route) lets a script served from `/serwist/sw.js` control
 * the whole origin, not just `/serwist/*`.
 *
 * Mounted once in `[locale]/layout.tsx`, alongside the other app-shell
 * providers (theme, query client, i18n).
 */
export function ServiceWorkerProvider({ children }: { children: ReactNode }) {
  return <SerwistProvider swUrl="/serwist/sw.js">{children}</SerwistProvider>;
}
