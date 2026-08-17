import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AdminReportsPanel } from "@/components/admin-reports-panel";
import { AdminStatsPanel } from "@/components/admin-stats-panel";

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
 * Admin Overview (FE-28/FE-29): stats + the reported-reviews queue, the
 * landing page of `/admin/*`. The auth+`is_admin` gate this page used to own
 * directly now lives in `@/app/[locale]/admin/layout.tsx` (FE-33) — it
 * covers this page and every route under `/admin/*` uniformly, so there is
 * nothing left to check here.
 *
 * `AdminUsersDirectoryPanel`/the former `AdminModerationPanel` (FE-30) no
 * longer render here — FE-33 moved the user directory to its own
 * `/admin/users` route (`@/app/[locale]/admin/users/page.tsx`), reachable
 * from the sidebar this layout now renders.
 *
 * The actual data fetch happens client-side in `AdminStatsPanel`
 * (`@/components/admin-stats-panel.tsx`) against `GET /api/admin/stats`
 * (`@/app/api/admin/stats/route.ts`), the Route Handler that injects the key
 * server-side. `AdminReportsPanel` (FE-29, `@/components/admin-reports-panel.tsx`)
 * follows the exact same client-fetch-against-a-BFF-route pattern for the
 * report queue, mounted below it on this same page.
 */
export default async function AdminPage({ params }: PageProps<"/[locale]/admin">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations("Admin");

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("heading")}</h1>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </div>

      <AdminStatsPanel />
      <AdminReportsPanel />
    </div>
  );
}
