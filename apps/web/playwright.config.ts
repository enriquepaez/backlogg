import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// Next 16 allows only one `next dev` per project directory, regardless of
// which port is requested — a second invocation refuses to start and just
// points at the already-running one (see `.next/dev/lock`, written by
// `node_modules/next/dist/build/lockfile.js`). Locally it's common to already
// have a dev server up (editor task, another terminal); detect it and reuse
// its port instead of hardcoding one, so `pnpm --filter web e2e` doesn't fail
// whenever that's the case. In CI there is no pre-existing lock (fresh
// checkout), so this is a no-op there.
function detectRunningDevServerPort(): string | undefined {
  if (process.env.CI) return undefined;
  try {
    const lockPath = path.join(__dirname, ".next/dev/lock");
    if (!existsSync(lockPath)) return undefined;
    const { port } = JSON.parse(readFileSync(lockPath, "utf8"));
    return typeof port === "number" ? String(port) : undefined;
  } catch {
    return undefined;
  }
}

const PORT = process.env.PLAYWRIGHT_PORT ?? detectRunningDevServerPort() ?? "3100";
const baseURL = `http://127.0.0.1:${PORT}`;

// `API_INTERNAL_URL` the Next server is started with — see the `webServer`
// array below. Was a bare unreachable address before FE-14 (nothing listened
// on it, so every `/v1` call from the app failed as a network error); now
// `e2e/mock-backend.mjs` actually listens here so `session-ux.spec.ts`
// (FE-14) can exercise the real server-side token-refresh/logout cycle. See
// that file's module doc comment for why `item-detail.spec.ts` /
// `browse.spec.ts`'s "backend unreachable" assertions still hold unchanged
// against it.
const MOCK_BACKEND_PORT = process.env.MOCK_BACKEND_PORT ?? "39999";

// Smoke E2E config (FE-7). Runs against `next dev` rather than a production
// `next build && next start`: this is a single "does the home page load"
// check, not a perf/production-parity suite, and `next dev` starts in ~1-2s
// vs a full production build — the CI job already builds the app separately
// (`pnpm --filter web build`, see `.github/workflows/ci.yml`), so a broken
// production build still fails CI even though Playwright itself boots dev.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // An array so both processes are started (and torn down) together for the
  // whole run — Playwright waits on each entry's readiness check before
  // running any test. See `e2e/mock-backend.mjs`'s doc comment for why a
  // single shared mock backend (rather than a second `next dev`) is the only
  // viable way to exercise a real `/v1/auth/refresh` round trip here: Next
  // only allows one `next dev` per project directory (see
  // `detectRunningDevServerPort` above), so there is exactly one Next server,
  // with one fixed `API_INTERNAL_URL`, for every spec file in this suite.
  webServer: [
    {
      command: `node e2e/mock-backend.mjs`,
      port: Number(MOCK_BACKEND_PORT),
      reuseExistingServer: false,
      timeout: 30_000,
      env: { MOCK_BACKEND_PORT },
    },
    {
      command: `pnpm exec next dev --port ${PORT}`,
      url: baseURL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        API_INTERNAL_URL: `http://127.0.0.1:${MOCK_BACKEND_PORT}`,
      },
    },
  ],
});
