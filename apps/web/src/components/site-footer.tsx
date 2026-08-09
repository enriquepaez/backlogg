import { getTranslations } from "next-intl/server";

export async function SiteFooter() {
  const t = await getTranslations("Footer");
  const year = new Date().getFullYear();

  return (
    <footer className="border-t border-border bg-background">
      <div className="mx-auto w-full max-w-5xl px-6 py-6 text-sm text-muted-foreground sm:px-10">
        {t("rights", { year })}
      </div>
    </footer>
  );
}
