import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { FeedEntryList } from "@/components/feed-entry-list";
import { FeedPagination } from "@/components/feed-pagination";
import { FeedTabs } from "@/components/feed-tabs";
import { redirect } from "@/i18n/navigation";
import { getCurrentUser } from "@/lib/api-fetch";
import { DEFAULT_FEED_TAB, getFeed, isFeedTab, type FeedTab } from "@/lib/feed";

/** Page size for the feed — matches `REVIEWS_PAGE_SIZE` (`/u/{username}`) for a consistent list length. */
const FEED_PAGE_SIZE = 20;

type RawParam = string | string[] | undefined;

function firstValue(value: RawParam): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseTab(value: RawParam): FeedTab {
  const raw = firstValue(value);
  return raw && isFeedTab(raw) ? raw : DEFAULT_FEED_TAB;
}

function parsePage(value: RawParam): number {
  const raw = firstValue(value);
  const parsed = raw ? Number.parseInt(raw, 10) : 1;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : 1;
}

/** OG metadata for `/feed` (FE-23), same shape as `/settings`'s `generateMetadata` (FE-17) — private, per-account page, never worth indexing. */
export async function generateMetadata({
  params,
}: PageProps<"/[locale]/feed">): Promise<Metadata> {
  const { locale } = await params;
  const tm = await getTranslations({ locale, namespace: "Metadata.feed" });
  const title = tm("title");
  const description = tm("description");

  return {
    title,
    description,
    robots: { index: false, follow: false },
    openGraph: { title, description, type: "website" },
  };
}

/**
 * Activity feed (FE-23), `/feed`: `following`/`popular` tabs over
 * `GET /v1/feed`. Protected route — `proxy.ts` already redirects
 * unauthenticated requests away at the edge (`lib/auth/protected-routes.ts`
 * lists `/feed`), but that check only looks at cookie PRESENCE, not
 * validity — this page still calls `getCurrentUser()` itself (the real,
 * server-side session check) and redirects to `/login` on `null`, same
 * defense-in-depth `settings/page.tsx`'s doc comment describes for every
 * private route.
 *
 * `tab` is parsed through {@link isFeedTab} before ever reaching
 * `getFeed`/the backend — an unrecognized `tab` value (typed directly into
 * the URL; the UI itself, `FeedTabs`, only ever links to the two valid
 * values) silently falls back to {@link DEFAULT_FEED_TAB} rather than
 * forwarding it and surfacing the backend's 422.
 */
export default async function FeedPage({
  params,
  searchParams,
}: PageProps<"/[locale]/feed">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const user = await getCurrentUser();
  if (!user) {
    redirect({ href: "/login", locale });
    return;
  }

  const query = await searchParams;
  const tab = parseTab(query.tab);
  const page = parsePage(query.page);

  const [t, result] = await Promise.all([
    getTranslations("Feed"),
    getFeed({ tab, page, limit: FEED_PAGE_SIZE }),
  ]);

  const totalPages = result.ok ? Math.max(1, Math.ceil(result.total / result.limit)) : 1;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("heading")}</h1>

      <FeedTabs tab={tab} />

      {!result.ok ? (
        <p role="alert" className="text-sm text-destructive">
          {t("error")}
        </p>
      ) : result.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {tab === "following" ? t("emptyFollowing") : t("emptyPopular")}
        </p>
      ) : (
        <>
          <FeedEntryList entries={result.items} locale={locale} />
          <FeedPagination tab={tab} page={result.page} totalPages={totalPages} />
        </>
      )}
    </div>
  );
}
