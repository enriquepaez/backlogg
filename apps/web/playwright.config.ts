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
  webServer: {
    command: `pnpm exec next dev --port ${PORT}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      // Present but deliberately unreachable: exercises the same
      // "backend unreachable -> render as anonymous" fallback documented in
      // `src/lib/api-fetch.ts` (`getCurrentUser`) and
      // `src/lib/auth/proxy-refresh.ts` (`refreshBeforeRender`), instead of
      // depending on a real backend just to smoke-test that the home page
      // renders.
      API_INTERNAL_URL: "http://127.0.0.1:39999",
    },
  },
});
