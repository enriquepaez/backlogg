import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Unit/integration tests (Vitest + Testing Library). End-to-end tests live
// under `e2e/` and run through Playwright instead (see `playwright.config.ts`)
// — they are excluded below so the two runners never pick up each other's
// spec files.
export default defineConfig({
  plugins: [react()],
  resolve: {
    // Resolves the `@/*` alias declared in tsconfig.json (Vite 8 supports
    // this natively; no need for the `vite-tsconfig-paths` plugin).
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["**/node_modules/**", "**/.next/**", "e2e/**"],
  },
});
