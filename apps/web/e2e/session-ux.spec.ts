import { expect, test } from "@playwright/test";

/**
 * Must match `VALID_REFRESH_TOKEN` in `e2e/mock-backend.mjs`. Not imported
 * directly: Playwright's test loader compiles `.spec.ts` files to CJS, which
 * cannot load that file's native-ESM `import.meta.url` self-execution guard.
 */
const VALID_REFRESH_TOKEN = "e2e-valid-refresh-token";

/**
 * FE-14 session UX: the transparent access-token refresh cycle and the
 * logout flow, both exercised through the REAL `proxy.ts` /
 * `/api/auth/logout` Route Handler running against `e2e/mock-backend.mjs`
 * (see `playwright.config.ts`'s `webServer` array and that file's doc
 * comment for why a shared mock backend is used instead of a live one).
 *
 * `/library` (one of `PROTECTED_PREFIXES`, `src/lib/auth/protected-routes.ts`)
 * has no page of its own yet — a valid session still reaches Next's routing
 * (and falls through to the `[...rest]` catch-all's `notFound()`), while an
 * invalid/missing session never gets that far: `proxy.ts` redirects to
 * `/{locale}/login` before any page renders. The assertion in every case
 * below is on the FINAL URL, which is enough to tell the two apart without
 * depending on how the not-found boundary itself renders (a `next dev`
 * quirk already worked around the same way in `browse.spec.ts` /
 * `item-detail.spec.ts`).
 */
test.describe("session UX", () => {
  test("a valid refresh token with no access token cookie refreshes transparently on a protected route", async ({
    context,
    page,
  }) => {
    await context.addCookies([
      {
        name: "bl_refresh",
        value: VALID_REFRESH_TOKEN,
        domain: "127.0.0.1",
        path: "/",
        httpOnly: true,
      },
    ]);

    const response = await page.goto("/en/library");

    expect(response?.status()).toBe(200);
    expect(new URL(page.url()).pathname).toBe("/en/library");

    // The proxy rotated the pair before the page rendered (`refreshBeforeRender`
    // in `src/lib/auth/proxy-refresh.ts`) — both cookies are now present and
    // the refresh token has changed (rotation), proving a real round trip to
    // `/v1/auth/refresh` happened rather than the fail-open "skipped" path.
    const cookies = await context.cookies();
    const access = cookies.find((c) => c.name === "bl_access");
    const refresh = cookies.find((c) => c.name === "bl_refresh");
    expect(access?.value).toBeTruthy();
    expect(refresh?.value).toBeTruthy();
    expect(refresh?.value).not.toBe(VALID_REFRESH_TOKEN);
  });

  test("no valid refresh token redirects a protected route to login", async ({ page }) => {
    // No cookies at all — the simplest "no session" case per
    // `isProtectedPath`'s check in `src/proxy.ts` (presence of `bl_refresh`).
    await page.goto("/en/library");

    expect(new URL(page.url()).pathname).toBe("/en/login");
  });

  test("an expired/invalid refresh token also redirects a protected route to login", async ({
    context,
    page,
  }) => {
    await context.addCookies([
      {
        name: "bl_refresh",
        value: "not-a-real-refresh-token",
        domain: "127.0.0.1",
        path: "/",
        httpOnly: true,
      },
    ]);

    await page.goto("/en/library");

    expect(new URL(page.url()).pathname).toBe("/en/login");

    // `refreshBeforeRender` clears the (rejected) cookie rather than leaving
    // a dead one behind.
    const cookies = await context.cookies();
    expect(cookies.find((c) => c.name === "bl_refresh")).toBeUndefined();
  });

  test("logout clears the session and a subsequent protected navigation redirects to login", async ({
    context,
    page,
  }) => {
    // Seed an already-authenticated session directly (login itself is FE-13's
    // concern) — any `access-`-prefixed token satisfies the mock backend's
    // `/v1/users/me`.
    await context.addCookies([
      {
        name: "bl_access",
        value: "access-e2e-seed-token",
        domain: "127.0.0.1",
        path: "/",
        httpOnly: true,
      },
      {
        name: "bl_refresh",
        value: VALID_REFRESH_TOKEN,
        domain: "127.0.0.1",
        path: "/",
        httpOnly: true,
      },
    ]);

    await page.goto("/en");
    const accountMenu = page.getByRole("button", { name: "Account menu" });
    await expect(accountMenu).toBeVisible();

    await accountMenu.click();
    await page.getByRole("menuitem", { name: /log out/i }).click();

    // The header re-renders anonymous (`router.refresh()` in `useLogout`).
    await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();

    const cookies = await context.cookies();
    expect(cookies.find((c) => c.name === "bl_access")).toBeUndefined();
    expect(cookies.find((c) => c.name === "bl_refresh")).toBeUndefined();

    await page.goto("/en/library");
    expect(new URL(page.url()).pathname).toBe("/en/login");
  });
});
