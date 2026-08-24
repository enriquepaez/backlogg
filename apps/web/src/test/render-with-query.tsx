import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

/**
 * Test-only `QueryClient` for the widgets migrated to TanStack Query (FE-48:
 * `rating-widget.tsx`, `viewer-status-slot.tsx`, `notification-bell.tsx`,
 * `library-status-counts.tsx`). Mirrors
 * `query-provider.tsx`'s real `retry: false`/`refetchOnWindowFocus: false`
 * defaults (same reasoning: a mocked MSW failure response should surface
 * immediately as the component's own error state, not after retries/backoff
 * that would make failure-path assertions slow or flaky) plus `gcTime: 0` —
 * unlike the app itself, every test gets a *fresh* client (see
 * `renderWithQuery` below), so there is nothing to garbage-collect between
 * tests and no reason to hold cached data across them.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        gcTime: 0,
      },
    },
  });
}

/**
 * `render` from Testing Library, wrapped in a fresh `QueryClientProvider`
 * per call — every one of this feature's widget tests renders through this
 * instead of `@testing-library/react`'s own `render`, the same way they
 * already share `@/test/msw/server` for network mocking. A fresh
 * `QueryClient` per render (not a module-level singleton) keeps every test
 * isolated: no cached query data or invalidation state leaks from one test
 * into the next, matching `query-provider.tsx`'s own "one `QueryClient` per
 * request" rationale.
 */
export function renderWithQuery(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
): RenderResult {
  const queryClient = createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  return render(ui, { wrapper: Wrapper, ...options });
}
