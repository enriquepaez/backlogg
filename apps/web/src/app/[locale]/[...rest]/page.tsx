import { notFound } from "next/navigation";
import { setRequestLocale } from "next-intl/server";

/**
 * Catch-all for any sub-path under `/[locale]/...` that doesn't match a more
 * specific route. Next.js route matching always prefers a literal/static
 * segment (e.g. `/[locale]/showcase`) over a catch-all like this one, so it
 * only fires for genuinely unmatched paths.
 *
 * Without this file, an arbitrary unmatched path (typo'd URL, dead link)
 * falls through to Next's built-in generic 404 instead of our localized
 * `[locale]/not-found.tsx` — there is no route file here to call
 * `notFound()` from, so nothing ever triggers the sibling `not-found.tsx`
 * boundary. Confirmed by hitting `/en/this-page-does-not-exist` before this
 * file existed: it returned Next's default "This page could not be found"
 * HTML, not our page.
 */
export default async function CatchAll({
  params,
}: PageProps<"/[locale]/[...rest]">) {
  const { locale } = await params;
  setRequestLocale(locale);
  notFound();
}
