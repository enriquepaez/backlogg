import { setupServer } from "msw/node";

import { handlers } from "./handlers";

/**
 * Node-side MSW server. Started/reset/stopped globally from
 * `src/test/setup.ts` so every Vitest file gets a working `/v1` mock without
 * remembering to wire it up — tests that need a different response for a
 * single case can call `server.use(...)` to override a handler just for that
 * test (it's reset automatically in `afterEach`).
 */
export const server = setupServer(...handlers);
