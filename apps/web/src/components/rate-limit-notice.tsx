"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { useRouter } from "@/i18n/navigation";

export type RateLimitNoticeProps = {
  /**
   * Seconds parsed from the backend's `Retry-After` header
   * (`docs/api.md`: `/v1/search`'s external-fallback rate limit), or `null`
   * if the header was missing/unparseable.
   */
  retryAfterSeconds: number | null;
};

/**
 * Shown in place of results when `/v1/search` answers 429 (FE-11
 * acceptance: "429 con Retry-After surfaced con UX de espera"). Counts down
 * the exact `Retry-After` value the backend sent instead of guessing or
 * polling — no `fetch`/navigation of any kind happens from this component
 * while the countdown is running. Once it reaches zero, the only way to
 * retry is the user clicking the button below (`router.refresh()`,
 * re-running the search page's Server Component fetch against the current
 * URL): this deliberately never auto-retries, so a user who walks away
 * never causes a request the moment the cooldown lapses — see
 * `search-controls.tsx`'s doc comment for the sibling "debounce, don't spam
 * the rate limit" concern on the input side of this same feature.
 */
export function RateLimitNotice({ retryAfterSeconds }: RateLimitNoticeProps) {
  const t = useTranslations("Search.rateLimited");
  const router = useRouter();
  const [remaining, setRemaining] = useState(Math.max(0, retryAfterSeconds ?? 0));

  // Adjusted during render rather than in an effect (see
  // `search-controls.tsx`'s matching comment) whenever the server hands this
  // component a new `retryAfterSeconds` (e.g. a fresh 429 after a retry).
  const [syncedRetryAfterSeconds, setSyncedRetryAfterSeconds] = useState(retryAfterSeconds);
  if (retryAfterSeconds !== syncedRetryAfterSeconds) {
    setSyncedRetryAfterSeconds(retryAfterSeconds);
    setRemaining(Math.max(0, retryAfterSeconds ?? 0));
  }

  useEffect(() => {
    if (remaining <= 0) {
      return;
    }
    const timer = setTimeout(() => setRemaining((current) => Math.max(0, current - 1)), 1000);
    return () => clearTimeout(timer);
  }, [remaining]);

  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-lg border border-border bg-muted/40 p-4 text-sm"
    >
      <p>{remaining > 0 ? t("waiting", { seconds: remaining }) : t("ready")}</p>
      {remaining <= 0 ? (
        <Button type="button" variant="outline" size="sm" onClick={() => router.refresh()}>
          {t("retry")}
        </Button>
      ) : null}
    </div>
  );
}
