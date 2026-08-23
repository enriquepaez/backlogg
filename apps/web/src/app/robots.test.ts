// @vitest-environment node
//
// Pure-function test: `robots.ts` only reads `@/lib/env` (mocked here so
// `SITE_URL` is deterministic) and `@/i18n/routing` (no `server-only`
// dependency, imported for real).
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/env", () => ({
  env: { SITE_URL: "https://backlogg.example" },
}));

const { default: robots } = await import("./robots");

describe("robots", () => {
  it("allows the public catalog and points at the sitemap", () => {
    const result = robots();

    expect(result.rules).toEqual(
      expect.objectContaining({ userAgent: "*", allow: "/" }),
    );
    expect(result.sitemap).toBe("https://backlogg.example/sitemap.xml");
  });

  it("disallows the private/no-SEO-value routes for every locale", () => {
    const result = robots();
    const disallow = Array.isArray(result.rules)
      ? result.rules.flatMap((rule) => rule.disallow ?? [])
      : (result.rules.disallow ?? []);

    for (const locale of ["en", "es"]) {
      for (const segment of [
        "admin",
        "settings",
        "login",
        "register",
        "forgot-password",
        "reset-password",
        "verify-email",
        "offline",
        "showcase",
      ]) {
        expect(disallow).toContain(`/${locale}/${segment}`);
      }
    }
  });

  it("does not disallow the public catalog routes", () => {
    const result = robots();
    const disallow = Array.isArray(result.rules)
      ? result.rules.flatMap((rule) => rule.disallow ?? [])
      : (result.rules.disallow ?? []);

    for (const publicPath of ["/en/movie/dune-2021", "/en/browse/movie", "/en/u/someone"]) {
      expect(disallow).not.toContain(publicPath);
    }
  });
});
