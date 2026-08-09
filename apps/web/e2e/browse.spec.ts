import { expect, test } from "@playwright/test";

// FE-9 smoke test, same shallow "does it boot" spirit as `home.spec.ts`
// (FE-7/FE-8). The webServer's `API_INTERNAL_URL` is deliberately
// unreachable (see `playwright.config.ts`), so this also doubles as a live
// exercise of the error state: `listCatalog` (`src/lib/catalog.ts`) reports
// `ok: false` on a network failure, and the page renders `Browse.error`
// (distinct from the `Browse.empty` state) instead of throwing.
//
// No test here for an invalid `/browse/{type}` (the `notFound()` call in
// `browse/[type]/page.tsx`): under `next dev` (what this config's webServer
// runs, see `playwright.config.ts`), the not-found boundary's content never
// reaches the rendered DOM for a fully-dynamic route — confirmed to be a
// pre-existing framework/dev-mode quirk, not something specific to this
// route (the sibling `[locale]/[...rest]` catch-all reproduces it too). The
// `notFound()`-triggering logic itself (`isCatalogType`) is covered by the
// `isCatalogType` describe block in `src/lib/catalog.test.ts`.
test.describe("browse page", () => {
  test("GET /en/browse/movie responds 200, renders the heading, and shows the error state", async ({
    page,
  }) => {
    const response = await page.goto("/en/browse/movie");

    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("heading", { level: 1, name: "Movies" }),
    ).toBeVisible();
    await expect(page.getByRole("alert")).toBeVisible();
  });
});
