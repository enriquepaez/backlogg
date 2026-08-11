import { expect, test } from "@playwright/test";

// FE-10 smoke test, same shallow "does it boot" spirit as `browse.spec.ts`
// (FE-9). The webServer's `API_INTERNAL_URL` is deliberately unreachable
// (see `playwright.config.ts`), so every fetch to the backend fails as a
// network error — this exercises `getItemDetail`'s `status: "error"` path
// (`src/lib/catalog.ts`), i.e. the page's inline, retryable error state
// rather than a hard `notFound()`. That's the behaviour FE-10's acceptance
// criteria calls out explicitly: a transient failure to reach the backend
// must never be treated as a permanent 404.
//
// No test here for an invalid `/{type}/{slug}` (the `notFound()` call in
// `[type]/[slug]/page.tsx`) or for a genuine backend 404: same known
// `next dev` quirk documented in `browse.spec.ts` (the not-found boundary's
// content doesn't reach the rendered DOM under `next dev`'s fully-dynamic
// route rendering) — covered instead by `isCatalogType`/`getItemDetail`'s
// `status: "not-found"` case in `src/lib/catalog.test.ts`.
test.describe("item detail page", () => {
  test("GET /en/movie/dune-2021 responds 200 and shows the error state", async ({
    page,
  }) => {
    const response = await page.goto("/en/movie/dune-2021");

    expect(response?.status()).toBe(200);
    await expect(page.getByRole("alert")).toBeVisible();
  });
});
