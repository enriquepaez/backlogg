"use client";

import { useLocale, useTranslations } from "next-intl";
import { Languages } from "lucide-react";

import { usePathname, useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { Button } from "@/components/ui/button";

export function LanguageSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  // `usePathname` from next-intl returns the pathname without the locale
  // prefix, so switching the locale keeps the user on the same page.
  const pathname = usePathname();
  const t = useTranslations("LanguageSwitcher");

  return (
    <div
      role="group"
      aria-label={t("label")}
      className="inline-flex items-center gap-1 rounded-lg border border-border p-1"
    >
      <Languages
        className="mx-1 size-4 text-muted-foreground"
        aria-hidden="true"
      />
      {routing.locales.map((value) => {
        const active = value === locale;
        return (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={active ? "secondary" : "ghost"}
            aria-pressed={active}
            onClick={() => router.replace(pathname, { locale: value })}
          >
            {t(value)}
          </Button>
        );
      })}
    </div>
  );
}
