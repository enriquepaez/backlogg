import type { components } from "@backlogg/api-client";

import { apiFetch } from "./api-fetch";
import { authHeader } from "./auth/session";
import type { CatalogType } from "./catalog-types";

/**
 * Personalized recommendations data source (FE-27), `GET /v1/recommendations`
 * — auth required (`docs/api.md`, "Recommendations (personalizadas)"). Same
 * skeleton as `./feed.ts`/`./notifications.ts`: built on `apiFetch`, which
 * reads the access-token cookie and retries once through a refresh on a 401,
 * safe to call directly from Server Component render.
 *
 * No `import "server-only"` of its own — same reasoning as `./feed.ts`: the
 * guard already lives in `./api-fetch.ts`/`./auth/session.ts`, both imported
 * here, so this module inherits it transitively.
 *
 * Reuses `CatalogType` (`./catalog-types.ts`) for the `?type=` filter instead
 * of declaring a parallel union — the backend's `RecommendationTypeFilter`
 * enum (`movie`/`series`/`book`/`game`) is exactly the same vocabulary as the
 * browse/trending route-segment type.
 *
 * This module used to export a `recommendationItemType(item)` that mapped a
 * result's uppercase `item_type` down to that vocabulary with a bare cast
 * (`item.item_type.toLowerCase() as CatalogType`) — issue #33. It is gone:
 * `toCatalogType` (`./catalog-types.ts`) is the one shared, guarded mapping,
 * and the page calls it with `item.item_type` like every other surface does.
 */

export type Recommendation = components["schemas"]["RecommendationOut"];
type RecommendationsOut = components["schemas"]["RecommendationsOut"];

/**
 * The exact `reason` the backend sends for every result when the caller has
 * no seeds (no `score >= 4` ratings and nothing `completed`/`want` in their
 * library) — `docs/api.md` and `backlogg/recommendations/service.py`'s
 * `_row_to_rec(..., "Popular right now")` call. Used by the page to detect
 * the no-seeds fallback and surface it as an informational state rather than
 * an error (FE-27 acceptance criterion), on top of each card already showing
 * its own `reason` text.
 */
export const RECOMMENDATIONS_FALLBACK_REASON = "Popular right now";

export type RecommendationsQuery = {
  type?: CatalogType;
  page?: number;
  limit?: number;
};

/**
 * Unlike `./feed.ts`/`./notifications.ts` (whose list responses include
 * `total`), `RecommendationsOut` only ever returns `results`/`page`/`limit`
 * — recommendations are computed on the fly, not counted ahead of time
 * (`docs/api.md`). Callers infer "is there a next page" from whether this
 * page came back full (`results.length === limit`) — see
 * `RecommendationsPagination`.
 */
export type RecommendationsPageResult =
  | { ok: true; results: Recommendation[]; page: number; limit: number }
  | { ok: false };

/** `GET /v1/recommendations?type=&page=&limit=` (`docs/api.md`). */
export async function getRecommendations(
  query: RecommendationsQuery = {},
): Promise<RecommendationsPageResult> {
  try {
    const { data, response } = await apiFetch<RecommendationsOut>((client, token) =>
      client.GET("/v1/recommendations", {
        params: { query: { type: query.type, page: query.page, limit: query.limit } },
        headers: authHeader(token),
      }),
    );
    return response.status === 200 && data ? { ok: true, ...data } : { ok: false };
  } catch (error) {
    console.error("getRecommendations: failed to reach the API", error);
    return { ok: false };
  }
}
