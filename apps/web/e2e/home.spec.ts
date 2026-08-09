import { expect, test } from "@playwright/test";

// Smoke test (FE-7 acceptance: "Playwright configurado con un e2e de humo
// (home carga)"). Deliberately shallow — this only proves the app boots,
// renders, and next-intl's locale routing works end-to-end; page-specific
// behaviour is covered by future feature work (FE-8+).
test.describe("home page", () => {
  test("GET /en responds 200 and renders the hero heading", async ({
    page,
  }) => {
    const response = await page.goto("/en");

    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Track everything you watch, read and play.",
      }),
    ).toBeVisible();
  });

  test("GET / redirects to the default locale and still renders the hero", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/en\/?$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });
});
