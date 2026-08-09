import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./msw/server";

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
