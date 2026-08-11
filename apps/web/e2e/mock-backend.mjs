import { createServer } from "node:http";
import { randomUUID } from "node:crypto";

/**
 * Minimal stand-in for the FastAPI backend, used ONLY by the Playwright e2e
 * suite (`playwright.config.ts`'s `webServer` array) so `session-ux.spec.ts`
 * (FE-14) can exercise the REAL server-side token-refresh cycle
 * (`src/lib/auth/proxy-refresh.ts`, run inside `src/proxy.ts`) and logout
 * flow end-to-end, without depending on a live backend + database in CI.
 *
 * Next.js only allows a single `next dev` instance per project directory
 * (see `playwright.config.ts`'s `detectRunningDevServerPort` comment), so
 * there is exactly one Next server for the whole e2e run, with a single
 * fixed `API_INTERNAL_URL`. That means this same mock backend is also what
 * `item-detail.spec.ts` / `browse.spec.ts` hit for their catalog fetches —
 * every path this server does NOT explicitly implement below answers `503`,
 * which `src/lib/catalog.ts`'s helpers (`getItemDetail`/`listCatalog`/etc.)
 * treat exactly like the previous "connection refused" backend (any
 * non-200/404 response maps to the same `"error"`/`ok:false` outcome), so
 * those specs' assertions are unaffected by this change.
 *
 * Auth model (deliberately simplified — this is not a security test):
 * - `VALID_REFRESH_TOKEN` is always accepted by `/v1/auth/refresh`, plus any
 *   refresh token this server has itself issued (no real rotation
 *   invalidation, no reuse-detection — that behavior is backend/pytest
 *   territory, out of scope for this frontend suite).
 * - Any access token this server issues is prefixed `access-`; a request to
 *   `/v1/users/me` is treated as authenticated iff its Bearer token has that
 *   prefix. Tests that want to start "already logged in" without going
 *   through a refresh round-trip can just seed a `bl_access` cookie with any
 *   `access-...` value directly.
 */
export const VALID_REFRESH_TOKEN = "e2e-valid-refresh-token";

const MOCK_USER = {
  username: "e2euser",
  email: "e2e@example.com",
  display_name: "E2E User",
  bio: null,
  avatar_url: null,
  email_verified: true,
};

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return {};
  }
}

export function createMockBackend() {
  const issuedRefreshTokens = new Set([VALID_REFRESH_TOKEN]);

  return createServer(async (req, res) => {
    const { pathname } = new URL(req.url, "http://localhost");

    if (req.method === "POST" && pathname === "/v1/auth/refresh") {
      const body = await readJsonBody(req);
      if (!issuedRefreshTokens.has(body.refresh_token)) {
        json(res, 401, { detail: "Invalid or expired refresh token" });
        return;
      }
      const accessToken = `access-${randomUUID()}`;
      const refreshToken = `refresh-${randomUUID()}`;
      issuedRefreshTokens.add(refreshToken);
      json(res, 200, {
        access_token: accessToken,
        refresh_token: refreshToken,
        token_type: "bearer",
      });
      return;
    }

    if (req.method === "POST" && pathname === "/v1/auth/logout") {
      await readJsonBody(req);
      res.writeHead(204);
      res.end();
      return;
    }

    if (req.method === "GET" && pathname === "/v1/users/me") {
      const auth = req.headers.authorization ?? "";
      const token = auth.startsWith("Bearer ") ? auth.slice("Bearer ".length) : "";
      if (token.startsWith("access-")) {
        json(res, 200, MOCK_USER);
      } else {
        json(res, 401, { detail: "Not authenticated" });
      }
      return;
    }

    // Everything else (catalog endpoints etc.): behave like a backend that
    // is up but broken, not like a hard 404 — see the module doc comment.
    json(res, 503, { detail: "not implemented in the e2e mock backend" });
  });
}

// Allow running directly as a Playwright `webServer` command:
// `node e2e/mock-backend.mjs`. `MOCK_BACKEND_PORT` mirrors `PLAYWRIGHT_PORT`
// (see `playwright.config.ts`).
if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.env.MOCK_BACKEND_PORT ?? 39999);
  const server = createMockBackend();
  server.listen(port, "127.0.0.1", () => {
    console.log(`mock-backend listening on http://127.0.0.1:${port}`);
  });
}
