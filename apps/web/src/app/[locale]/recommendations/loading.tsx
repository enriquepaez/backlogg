/**
 * Route-level loading UI for `/recommendations` (FE-27), shown by Next while
 * the page's data fetch (`getRecommendations`) is in flight during a
 * navigation to this segment. Skeleton poster cards echo the eventual grid
 * layout, same pattern as `/trending`'s and `/browse/{type}`'s `loading.tsx`
 * (FE-9/FE-12).
 */
export default function RecommendationsLoading() {
  return (
    <div
      role="status"
      className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16"
    >
      <div className="h-9 w-56 animate-pulse rounded-md bg-muted" />
      <div className="h-8 w-40 animate-pulse rounded-lg bg-muted" />
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {Array.from({ length: 12 }, (_, index) => (
          <div key={index} className="aspect-2/3 w-full animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    </div>
  );
}
