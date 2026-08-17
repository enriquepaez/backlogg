import { getTranslations, setRequestLocale } from "next-intl/server";

import { AdminComingSoon } from "@/components/admin-coming-soon";

/**
 * `/admin/series` (FE-33): stub, reachable from `<AdminSidebar>` but with no
 * functionality yet — FE-34 (`admin_catalog_backoffice`) fills this in. Same
 * shape as its `movies`/`books`/`games` siblings — see
 * `@/app/[locale]/admin/movies/page.tsx`'s own doc comment.
 */
export default async function AdminSeriesStubPage({
  params,
}: PageProps<"/[locale]/admin/series">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: "Admin.sidebar" });

  return <AdminComingSoon section={t("series")} />;
}
