/**
 * Route-level loading UI for `/browse/{type}` (FE-9), shown by Next while
 * the page's data fetches (`listCatalog`/`getGenres`) are in flight during a
 * navigation to this segment. Skeleton poster cards echo the eventual grid
 * layout (`grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6`, see
 * `page.tsx`) instead of the app shell's generic spinner
 * (`[locale]/loading.tsx`) — this segment's `loading.tsx` takes priority
 * over the parent's for navigations into `/browse/{type}`.
 */
export default function BrowseLoading() {
  return (
    <div
      role="status"
      className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16"
    >
      <div className="h-9 w-48 animate-pulse rounded-md bg-muted" />
      <div className="flex gap-4">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-muted" />
        <div className="h-8 w-40 animate-pulse rounded-lg bg-muted" />
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {Array.from({ length: 12 }, (_, index) => (
          <div key={index} className="aspect-2/3 w-full animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    </div>
  );
}
