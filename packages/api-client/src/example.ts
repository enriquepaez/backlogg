// Type-level acceptance demo for the generated client.
//
// This file is NOT meant to run against a live backend — it exists so the
// type checker proves that a typed `GET /v1/movies` call resolves to the
// correct response shape. Accessing fields with explicit expected types below
// means a regression in the generated schema (e.g. `total` stops being a
// number) would break `pnpm --filter @backlogg/api-client typecheck`.

import { createApiClient, type components } from "./index.js";

type MovieListOut = components["schemas"]["MovieListOut"];
type MovieListItemOut = components["schemas"]["MovieListItemOut"];

export async function listTopScienceFictionMovies(): Promise<MovieListItemOut[]> {
  const api = createApiClient("http://localhost:8000");

  const { data, error } = await api.GET("/v1/movies", {
    // Query params are typed from the OpenAPI operation; unknown keys or wrong
    // value types would fail the build here.
    params: {
      query: {
        genre: "science-fiction",
        sort: "rating_desc",
        page: 1,
        limit: 20,
      },
    },
  });

  if (error || !data) {
    return [];
  }

  // `data` is typed as MovieListOut. These assignments pin the field types so a
  // schema drift is caught at compile time.
  const page: MovieListOut = data;
  const total: number = page.total;
  const title: string = page.items[0]?.title ?? "";
  void total;
  void title;

  return page.items;
}
