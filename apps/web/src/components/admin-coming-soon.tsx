import { getTranslations } from "next-intl/server";

export type AdminComingSoonProps = {
  /** Already-translated section heading (e.g. `t("sidebar.movies")`) — see each stub page's own doc comment. */
  section: string;
};

/**
 * Shared "coming soon" body for the four catalog backoffice stubs FE-33
 * introduces (`/admin/movies`, `/admin/series`, `/admin/books`,
 * `/admin/games`) — navigable from `<AdminSidebar>` but with no
 * functionality yet; FE-34 (`admin_catalog_backoffice`, `depends_on` this
 * feature) fills them in. A single shared component rather than four copies
 * of the same two-line markup, one per stub page.
 */
export async function AdminComingSoon({ section }: AdminComingSoonProps) {
  const t = await getTranslations("Admin");

  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-2xl font-semibold tracking-tight">{section}</h1>
      <p className="text-sm text-muted-foreground">{t("comingSoon")}</p>
    </div>
  );
}
