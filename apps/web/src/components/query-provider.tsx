"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A small default staleTime avoids refetching immediately on the
        // client right after a Server Component already fetched fresh data.
        staleTime: 60 * 1000,
        // FE-48: every "personal widget" query (rating, library status,
        // notifications, profile library counts) is a thin proxy over a
        // BFF route that itself proxies `/v1` — a failure there
        // is either a genuine backend error or "no session", neither of
        // which gets better on its own. The 4 widgets this powers all
        // pre-dated TanStack Query and fetched exactly once with no retry,
        // showing their own `load-error`/error state immediately on
        // failure; keeping `retry: false` as the app-wide default preserves
        // that behavior (and keeps failure-path tests fast/deterministic)
        // instead of TanStack Query's own default of 3 retries with
        // exponential backoff.
        retry: false,
        // Same rationale, the other half of it: none of those widgets ever
        // silently refetched on window refocus before (each only fetched
        // once, on mount) — several of them hold in-progress form state
        // (`RatingWidget`'s score/review composer) that a background
        // refetch has no way to distinguish from a stale read, so a
        // refocus-triggered refetch could otherwise
        // clobber `queryClient.setQueryData` writes those widgets make
        // right after a successful mutation. Explicit invalidation (FE-48's
        // cross-widget `library_counts` case) still refetches normally —
        // this only turns off the automatic "the browser tab regained
        // focus" trigger.
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function QueryProvider({ children }: { children: ReactNode }) {
  // One `QueryClient` PER REQUEST, created lazily via `useState`. This file
  // renders on the server for the initial HTML too (it is mounted from
  // `[locale]/layout.tsx`), so a module-level singleton would be shared
  // across unrelated requests/users on the server and leak cached query
  // state between them. `useState`'s initializer only runs once per
  // component instance, which is exactly "once per request" on the server
  // and "once per page load" on the client — the standard TanStack Query
  // pattern for the Next.js App Router.
  const [queryClient] = useState(makeQueryClient);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
