// Regenerates the typed API client from the backend's OpenAPI schema.
//
// Steps:
//   1. Export the OpenAPI document from the Python backend (introspection only,
//      no database needed) into ./openapi.json.
//   2. Run openapi-typescript over that document to (re)generate ./src/schema.d.ts.
//
// Run with: pnpm --filter @backlogg/api-client gen:api
// After running, re-commit both openapi.json and src/schema.d.ts.

import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const packageDir = resolve(scriptDir, "..");
const repoRoot = resolve(packageDir, "..", "..");

const openapiPath = resolve(packageDir, "openapi.json");
const schemaPath = resolve(packageDir, "src", "schema.d.ts");

const PY_EXPORT =
  "import json,backlogg.main as m; print(json.dumps(m.app.openapi(), indent=2))";

console.log("[gen:api] Exporting OpenAPI schema from backend...");
const openapiJson = execFileSync("uv", ["run", "python", "-c", PY_EXPORT], {
  cwd: repoRoot,
  encoding: "utf8",
  maxBuffer: 64 * 1024 * 1024,
  stdio: ["ignore", "pipe", "inherit"],
});

// Sanity check: must be valid JSON with paths before we overwrite anything.
const parsed = JSON.parse(openapiJson);
const pathCount = Object.keys(parsed.paths ?? {}).length;
if (pathCount === 0) {
  throw new Error("[gen:api] Exported schema has no paths; aborting.");
}

writeFileSync(openapiPath, openapiJson.endsWith("\n") ? openapiJson : openapiJson + "\n");
console.log(`[gen:api] Wrote ${openapiPath} (${pathCount} paths).`);

console.log("[gen:api] Generating TypeScript types...");
execFileSync(
  "pnpm",
  ["exec", "openapi-typescript", openapiPath, "-o", schemaPath],
  { cwd: packageDir, stdio: "inherit" },
);
console.log(`[gen:api] Wrote ${schemaPath}.`);
console.log("[gen:api] Done. Re-commit openapi.json and src/schema.d.ts.");
