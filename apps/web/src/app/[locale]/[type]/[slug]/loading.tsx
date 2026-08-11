/**
 * Route-level loading UI for `/{type}/{slug}` (FE-10), shown by Next while
 * the page's data fetches (`getItemDetail`/`getSimilarItems`) are in flight
 * during a navigation to this segment. Echoes `ItemHero`'s layout (poster +
 * title/metadata column), same pattern as `browse/[type]/loading.tsx` (FE-9).
 */
export default function ItemDetailLoading() {
  return (
    <div
      role="status"
      className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-16 sm:flex-row"
    >
      <div className="aspect-2/3 w-48 shrink-0 animate-pulse rounded-xl bg-muted sm:w-64" />
      <div className="flex flex-1 flex-col gap-4">
        <div className="h-9 w-2/3 animate-pulse rounded-md bg-muted" />
        <div className="h-6 w-1/3 animate-pulse rounded-md bg-muted" />
        <div className="h-20 w-full animate-pulse rounded-md bg-muted" />
        <div className="h-16 w-2/3 animate-pulse rounded-md bg-muted" />
      </div>
    </div>
  );
}
