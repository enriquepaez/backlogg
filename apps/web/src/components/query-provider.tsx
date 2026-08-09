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
