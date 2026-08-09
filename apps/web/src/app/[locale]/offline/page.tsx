import { WifiOff } from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Minimal offline fallback (FE-6): what the service worker serves for any
 * page navigation that fails while offline and isn't otherwise answered
 * from the runtime cache (see the `fallbacks` option in `src/sw.ts`).
 *
 * Deliberately static — no data fetching — so it renders correctly from the
 * precache with no network at all. It's still reachable as a normal page at
 * `/{locale}/offline` (useful to preview without going offline), and the
 * shared `[locale]/layout.tsx` chrome (header/footer/theme) around it comes
 * from the same app-shell precache.
 */
export default async function OfflinePage({
  params,
}: PageProps<"/[locale]/offline">) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Offline");

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-24 text-center">
      <WifiOff className="size-8 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="max-w-md text-muted-foreground">{t("description")}</p>
      <Link href="/" className={cn(buttonVariants({ variant: "outline" }))}>
        {t("backHome")}
      </Link>
    </div>
  );
}
