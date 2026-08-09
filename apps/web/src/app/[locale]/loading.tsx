import { Loader2 } from "lucide-react";
import { getTranslations } from "next-intl/server";

export default async function Loading() {
  const t = await getTranslations("Loading");

  return (
    <div
      role="status"
      className="flex flex-1 items-center justify-center py-24"
    >
      <Loader2
        className="size-6 animate-spin text-muted-foreground"
        aria-hidden="true"
      />
      <span className="sr-only">{t("label")}</span>
    </div>
  );
}
