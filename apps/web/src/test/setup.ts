import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./msw/server";

// jsdom doesn't implement `Element.scrollIntoView` (it throws "not a
// function"). Radix's `Select` (`@/components/ui/select.tsx`, used by
// `AdminUsersDirectoryPanel`) calls it on the selected/first item when its
// content opens, so every test that opens a `Select` in jsdom needs this
// no-op stub. No layout happens in jsdom anyway, so a no-op is faithful.
// Guarded with `typeof Element` since this same setup file also runs for
// `// @vitest-environment node` suites (e.g. Route Handler tests), where
// there is no DOM at all.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// Testing Library doesn't auto-cleanup outside of Jest's global afterEach
// hook, so it's wired up explicitly here for Vitest.
afterEach(() => {
  cleanup();
});

// MSW intercepts `/v1` network calls for every test file (unit +
// integration) so nothing here ever depends on a real backend being up.
// `onUnhandledRequest: "error"` fails loudly if a test forgets to mock an
// endpoint it actually calls, instead of silently hitting the network.
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
