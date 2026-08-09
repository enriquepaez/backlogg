import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default async function NotFound() {
  const t = await getTranslations("NotFound");

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-24 text-center">
      <h2 className="text-2xl font-semibold tracking-tight">{t("title")}</h2>
      <p className="max-w-md text-muted-foreground">{t("description")}</p>
      <Link href="/" className={cn(buttonVariants({ variant: "outline" }))}>
        {t("backHome")}
      </Link>
    </div>
  );
}
