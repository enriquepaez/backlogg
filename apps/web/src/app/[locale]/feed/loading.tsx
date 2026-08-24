/**
 * Route-level loading UI for `/feed` (FE-52, production audit3
 * 2026-08-24), shown by Next while the page's data fetch (`getFeed`) is in
 * flight during a navigation to this segment — a high-traffic route that,
 * until now, fell back to the app shell's generic spinner
 * (`[locale]/loading.tsx`). Skeleton echoes `page.tsx`'s layout (heading +
 * `FeedTabs` + a list of entry cards, matching `FeedEntryList`'s vertical
 * `flex flex-col gap-4` stack rather than a grid), same pattern as
 * `browse/[type]/loading.tsx` (FE-9).
 */
export default function FeedLoading() {
  return (
    <div
      role="status"
      className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 py-16"
    >
      <div className="h-9 w-32 animate-pulse rounded-md bg-muted" />
      <div className="flex gap-2">
        <div className="h-8 w-28 animate-pulse rounded-lg bg-muted" />
        <div className="h-8 w-28 animate-pulse rounded-lg bg-muted" />
      </div>
      <div className="flex flex-col gap-4">
        {Array.from({ length: 5 }, (_, index) => (
          <div key={index} className="h-32 w-full animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    </div>
  );
}
