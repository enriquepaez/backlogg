import { getTranslations, setRequestLocale } from "next-intl/server";

import { AdminComingSoon } from "@/components/admin-coming-soon";

/**
 * `/admin/books` (FE-33): stub, reachable from `<AdminSidebar>` but with no
 * functionality yet — FE-34 (`admin_catalog_backoffice`) fills this in. Same
 * shape as its `movies`/`series`/`games` siblings — see
 * `@/app/[locale]/admin/movies/page.tsx`'s own doc comment.
 */
export default async function AdminBooksStubPage({
  params,
}: PageProps<"/[locale]/admin/books">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const t = await getTranslations({ locale, namespace: "Admin.sidebar" });

  return <AdminComingSoon section={t("books")} />;
}
