import { getTranslations, setRequestLocale } from "next-intl/server";

import { LanguageSwitcher } from "@/components/language-switcher";
import { ModeToggle } from "@/components/mode-toggle";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";

export default async function Home({ params }: PageProps<"/[locale]">) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Home");

  return (
    <div className="flex flex-1 flex-col bg-background">
      <header className="flex flex-wrap items-center justify-between gap-4 px-6 py-4 sm:px-10">
        <span className="text-lg font-semibold tracking-tight">
          {t("brand")}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <LanguageSwitcher />
          <ModeToggle />
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-8 px-6 py-16 text-center sm:items-start sm:text-left">
        <div className="flex flex-col gap-6">
          <h1 className="max-w-2xl text-4xl font-semibold leading-tight tracking-tight">
            {t("title")}
          </h1>
          <p className="max-w-xl text-lg leading-8 text-muted-foreground">
            {t("description")}
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button asChild>
            <Link href="/showcase">{t("exploreShowcase")}</Link>
          </Button>
          <Button asChild variant="outline">
            <a
              href="https://nextjs.org/docs"
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("documentation")}
            </a>
          </Button>
        </div>
      </main>
    </div>
  );
}
