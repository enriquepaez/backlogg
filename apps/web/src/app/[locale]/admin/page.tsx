import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AdminReportsPanel } from "@/components/admin-reports-panel";
import { AdminStatsPanel } from "@/components/admin-stats-panel";
import { redirect } from "@/i18n/navigation";
import { getCurrentUser } from "@/lib/api-fetch";

/** OG metadata for `/admin` (FE-28), same shape as `/settings`'s `generateMetadata` (FE-17). */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/admin">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.admin" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    // Private, operator-facing page — never worth indexing, same as
    // `/settings`/`/recommendations`.
    robots: { index: false, follow: false },
    openGraph: { title, description, type: "website" },
  };
}

/**
 * Admin dashboard (FE-28): minimal landing page for the `/v1/admin/*`
 * surface — a stats overview for now, extended by FE-29 (report queue) and
 * FE-30 (moderation actions) later.
 *
 * `proxy.ts` already redirects unauthenticated requests to `/admin` away at
 * the edge (`lib/auth/protected-routes.ts` lists it), but that check only
 * looks at cookie PRESENCE, not validity — this page still calls
 * `getCurrentUser()` itself (the real, server-side session check) and
 * redirects to `/login` on `null`, same defense-in-depth every other private
 * route uses (`/settings`, `/recommendations`, `/feed`).
 *
 * Real admin authorization (`admin_role_gate` fix, bundled onto this same
 * branch after FE-28 shipped): a signed-in session alone used to be enough
 * to reach this page, so ANY authenticated user could load it. `users` now
 * has a real `is_admin` column (`backlogg/users/models.py`, default `false`,
 * no API endpoint flips it — set by hand in the DB by an operator), exposed
 * on `UserMeOut` (`GET /v1/users/me`). A signed-in non-admin user
 * (`user.is_admin === false`) is redirected to `/` — NOT `/login`, since
 * they *are* authenticated, just not authorized for this section. This is
 * the actual authorization check; `/v1/admin/*` itself is still additionally
 * gated by the shared `X-API-Key` secret described below.
 *
 * The actual data fetch happens client-side in `AdminStatsPanel`
 * (`@/components/admin-stats-panel.tsx`) against `GET /api/admin/stats`
 * (`@/app/api/admin/stats/route.ts`), the Route Handler that injects the key
 * server-side. `AdminReportsPanel` (FE-29, `@/components/admin-reports-panel.tsx`)
 * follows the exact same client-fetch-against-a-BFF-route pattern for the
 * report queue, mounted below it on this same page — no changes needed here
 * beyond rendering it, since the auth guard above already covers everything
 * under `/admin`.
 */
export default async function AdminPage({ params }: PageProps<"/[locale]/admin">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const user = await getCurrentUser();
  if (!user) {
    redirect({ href: "/login", locale });
    return;
  }
  if (!user.is_admin) {
    redirect({ href: "/", locale });
    return;
  }

  const t = await getTranslations("Admin");

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("heading")}</h1>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </div>

      <AdminStatsPanel />
      <AdminReportsPanel />
    </div>
  );
}
