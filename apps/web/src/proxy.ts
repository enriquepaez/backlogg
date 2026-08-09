import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Match all pathnames except for API routes, Next internals and static
  // assets (anything with a dot). This is what runs the locale negotiation.
  matcher: "/((?!api|trpc|_next|_vercel|.*\\..*).*)",
};
