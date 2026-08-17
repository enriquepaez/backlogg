import { getTranslations, setRequestLocale } from "next-intl/server";

import { AdminComingSoon } from "@/components/admin-coming-soon";

/**
 * `/admin/movies` (FE-33): stub, reachable from `<AdminSidebar>` but with no
 * functionality yet — FE-34 (`admin_catalog_backoffice`) fills this in. Same
 * shape as its `series`/`books`/`games` siblings, sharing `AdminComingSoon`
 * (`@/components/admin-coming-soon.tsx`) for the body. The auth+`is_admin`
 * gate lives in `@/app/[locale]/admin/layout.tsx`, which wraps this route.
 */
export default async function AdminMoviesStubPage({
  params,
}: PageProps<"/[locale]/admin/movies">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: "Admin.sidebar" });

  return <AdminComingSoon section={t("movies")} />;
}
