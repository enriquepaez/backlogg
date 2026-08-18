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

// Node 22+'s own experimental `localStorage` global (a WHATWG Storage
// backed by a file, opt-in via `--localstorage-file`) shadows jsdom's
// window-scoped implementation without actually providing one when that
// flag is absent — `window.localStorage` (same object as `globalThis` in
// Vitest's jsdom environment) ends up `undefined` instead of a working
// `Storage`, even though jsdom itself normally implements it. First hit by
// `library-view-toggle.tsx` (FE-43), the first component in this codebase
// to read/write `localStorage` in a way its tests exercise. A minimal
// in-memory `Storage` polyfill, guarded the same way as the
// `scrollIntoView` shim above, keeps every test's `localStorage` isolated
// (cleared per test file's own `beforeEach`, same as a real fresh
// `Storage`) without depending on this Node/jsdom quirk being fixed
// upstream.
if (typeof window !== "undefined" && !window.localStorage) {
  const store = new Map<string, string>();
  const memoryStorage: Storage = {
    getItem: (key) => (store.has(key) ? store.get(key)! : null),
    setItem: (key, value) => {
      store.set(key, String(value));
    },
    removeItem: (key) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
    key: (index) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  };
  Object.defineProperty(window, "localStorage", { value: memoryStorage, configurable: true });
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
