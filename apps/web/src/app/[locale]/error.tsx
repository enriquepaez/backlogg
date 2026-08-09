"use client"; // Error boundaries must be Client Components.

import { useEffect } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

// Next 16.3 stabilized `retry` as the recovery prop (see
// `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md`,
// version history: "v16.3.0 | `retry` prop became stable" — older `reset`
// still exists but `retry` is now the recommended one).
export default function RouteError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  const t = useTranslations("ErrorPage");

  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-24 text-center">
      <h2 className="text-2xl font-semibold tracking-tight">{t("title")}</h2>
      <p className="max-w-md text-muted-foreground">{t("description")}</p>
      <Button type="button" onClick={() => retry()}>
        {t("retry")}
      </Button>
    </div>
  );
}
