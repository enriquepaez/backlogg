// @vitest-environment jsdom
//
// `fetchAdminCatalogItem`/`saveAdminCatalogItem` call this app's OWN
// `/api/admin/[type]/[slug]` route with a relative URL — MSW intercepts
// relative paths against `location.origin` in jsdom, same pattern as
// `admin-user-actions.ts`'s own test would use (that module has no
// dedicated test file, this establishes the pattern for both).
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";

import { server } from "@/test/msw/server";

import { fetchAdminCatalogItem, saveAdminCatalogItem } from "./admin-catalog";

const editOutFixture = {
  type: "movie",
  slug: "dune-2021",
  title: "Dune",
  poster_url: "https://example.com/dune.jpg",
  release_date: "2021-10-22",
  first_air_date: null,
  first_publish_date: null,
  genres: ["Science Fiction"],
  locked_fields: ["title"],
};

afterEach(() => {
  server.resetHandlers();
});

describe("fetchAdminCatalogItem", () => {
  it("PATCHes an empty body and returns the item on 200", async () => {
    let forwardedBody: unknown = null;
    server.use(
      http.patch("/api/admin/movie/dune-2021", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(editOutFixture, { status: 200 });
      }),
    );

    const result = await fetchAdminCatalogItem("movie", "dune-2021");

    expect(result).toEqual({ ok: true, item: editOutFixture });
    expect(forwardedBody).toEqual({});
  });

  it("URL-encodes the slug", async () => {
    let requestedUrl = "";
    server.use(
      http.patch("/api/admin/movie/:slug", ({ request, params }) => {
        requestedUrl = request.url;
        return HttpResponse.json({ ...editOutFixture, slug: params.slug as string }, { status: 200 });
      }),
    );

    await fetchAdminCatalogItem("movie", "a slug/with special");

    expect(requestedUrl).toContain(encodeURIComponent("a slug/with special"));
  });

  it.each([
    [401, "unauthorized"],
    [404, "not_found"],
    [503, "not_configured"],
    [422, "validation"],
    [500, "unknown"],
  ] as const)("maps a %i response to reason %s", async (status, reason) => {
    server.use(http.patch("/api/admin/movie/dune-2021", () => new HttpResponse(null, { status })));

    const result = await fetchAdminCatalogItem("movie", "dune-2021");

    expect(result).toEqual({ ok: false, reason });
  });

  it("maps a network failure to reason unknown", async () => {
    server.use(http.patch("/api/admin/movie/dune-2021", () => HttpResponse.error()));

    const result = await fetchAdminCatalogItem("movie", "dune-2021");

    expect(result).toEqual({ ok: false, reason: "unknown" });
  });
});

describe("saveAdminCatalogItem", () => {
  it("PATCHes the given payload and returns the item on 200", async () => {
    let forwardedBody: unknown = null;
    server.use(
      http.patch("/api/admin/movie/dune-2021", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(editOutFixture, { status: 200 });
      }),
    );

    const result = await saveAdminCatalogItem("movie", "dune-2021", { title: "Dune" });

    expect(result).toEqual({ ok: true, item: editOutFixture });
    expect(forwardedBody).toEqual({ title: "Dune" });
  });
});
