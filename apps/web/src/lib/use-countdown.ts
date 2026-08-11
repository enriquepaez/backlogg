"use client";

import { useEffect, useState } from "react";

/**
 * Ticks `seconds` down to zero, one second at a time. Whenever a new
 * `seconds` value is passed in (e.g. a fresh 429 with a new `Retry-After`),
 * the countdown restarts from it.
 *
 * The timer logic mirrors `components/rate-limit-notice.tsx` (FE-11), but is
 * extracted here rather than reused from there: that component's "retry"
 * action is `router.refresh()` (re-running a Server Component fetch), which
 * doesn't fit a client-only form's "the user resubmits the form" semantics
 * (FE-13's register/login 429 handling) — `register-form.tsx` / `login-form.tsx`
 * only need the countdown number to disable/re-enable their submit button.
 */
export function useCountdown(seconds: number | null): number {
  const [remaining, setRemaining] = useState(Math.max(0, seconds ?? 0));

  // Adjusted during render (same "derive state from props" pattern as
  // `rate-limit-notice.tsx` / `search-controls.tsx`) rather than in an
  // effect, so a new `seconds` value takes effect on the very render it
  // arrives instead of one tick late.
  const [synced, setSynced] = useState(seconds);
  if (seconds !== synced) {
    setSynced(seconds);
    setRemaining(Math.max(0, seconds ?? 0));
  }

  useEffect(() => {
    if (remaining <= 0) {
      return;
    }
    const timer = setTimeout(() => setRemaining((current) => Math.max(0, current - 1)), 1000);
    return () => clearTimeout(timer);
  }, [remaining]);

  return remaining;
}
