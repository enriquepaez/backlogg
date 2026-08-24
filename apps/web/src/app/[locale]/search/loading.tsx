/**
 * Route-level loading UI for `/search` (FE-52, production audit3
 * 2026-08-24), shown by Next while the page's data fetch (`searchCatalog`)
 * is in flight during a navigation to this segment — a high-traffic route
 * that, until now, fell back to the app shell's generic spinner
 * (`[locale]/loading.tsx`). Skeleton echoes `page.tsx`'s layout (heading +
 * `SearchControls` row + poster grid), same pattern as
 * `browse/[type]/loading.tsx` (FE-9).
 */
export default function SearchLoading() {
  return (
    <div
      role="status"
      className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16"
    >
      <div className="h-9 w-40 animate-pulse rounded-md bg-muted" />
      <div className="flex flex-wrap items-end gap-4">
        <div className="h-9 min-w-48 flex-1 animate-pulse rounded-md bg-muted" />
        <div className="h-9 w-32 animate-pulse rounded-lg bg-muted" />
        <div className="h-9 w-36 animate-pulse rounded-lg bg-muted" />
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {Array.from({ length: 12 }, (_, index) => (
          <div key={index} className="aspect-2/3 w-full animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    </div>
  );
}
