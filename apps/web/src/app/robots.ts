import type { MetadataRoute } from "next";

import { routing } from "@/i18n/routing";
import { env } from "@/lib/env";

/**
 * Route segments (immediately after the locale prefix) with no SEO value,
 * disallowed for every locale below. Two different reasons land a segment
 * here, same list `progress/current.md` (FE-46's plan) worked out from
 * `src/lib/auth/protected-routes.ts` + the auth-flow routes:
 *
 * - `admin`: gated backoffice (FE-28) — never meant to be indexed.
 * - `settings`: requires a session; nothing to crawl for an anonymous bot.
 * - `login`/`register`/`forgot-password`/`reset-password`/`verify-email`:
 *   auth-flow pages, no content, not worth a search result.
 * - `offline`: PWA-only fallback shell (FE-6), meaningless outside a service
 *   worker context.
 * - `showcase`: internal design-system kitchen sink (FE-3), never public
 *   content.
 *
 * Each entry is disallowed as a plain per-locale prefix (`/en/admin`, not a
 * `*` glob) — the Robots Exclusion Standard already treats a disallowed path
 * as a prefix match, so `/en/admin` alone also covers nested pages like
 * `/en/admin/users/{username}` without needing a wildcard.
 */
const DISALLOWED_SEGMENTS = [
  "admin",
  "settings",
  "login",
  "register",
  "forgot-password",
  "reset-password",
  "verify-email",
  "offline",
  "showcase",
] as const;

/**
 * `src/app/robots.ts` (FE-46): allows crawling the public catalog (home,
 * browse, item detail, search, genres/trending, public profiles) for every
 * locale, disallows the private/no-SEO-value routes above, and points
 * crawlers at `sitemap.ts`'s output.
 */
export default function robots(): MetadataRoute.Robots {
  const disallow = routing.locales.flatMap((locale) =>
    DISALLOWED_SEGMENTS.map((segment) => `/${locale}/${segment}`),
  );

  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow,
    },
    sitemap: `${env.SITE_URL}/sitemap.xml`,
  };
}
