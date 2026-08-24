/**
 * Route-level loading UI for `/u/{username}` (FE-52, production audit3
 * 2026-08-24), shown by Next while the page's data fetches
 * (`getUserProfile`/`getUserReviews`/`getUserLibrary`) are in flight during
 * a navigation to this segment — until now this fell back to the app
 * shell's generic spinner (`[locale]/loading.tsx`). Skeleton echoes
 * `page.tsx`'s layout (avatar + name header, library counts + poster
 * preview grid, reviews list), same pattern as `browse/[type]/loading.tsx`
 * (FE-9) and `[type]/[slug]/loading.tsx` (FE-10).
 */
export default function UserProfileLoading() {
  return (
    <div
      role="status"
      className="mx-auto flex w-full max-w-4xl flex-col gap-10 px-6 py-16"
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-4">
          <div className="size-16 animate-pulse rounded-full bg-muted" />
          <div className="flex flex-col gap-2">
            <div className="h-7 w-40 animate-pulse rounded-md bg-muted" />
            <div className="h-4 w-24 animate-pulse rounded-md bg-muted" />
          </div>
        </div>
        <div className="h-4 w-64 animate-pulse rounded-md bg-muted" />
      </div>

      <div className="flex flex-col gap-3">
        <div className="h-7 w-32 animate-pulse rounded-md bg-muted" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="h-16 w-full animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="aspect-2/3 w-full animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-4">
        <div className="h-7 w-32 animate-pulse rounded-md bg-muted" />
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index} className="h-24 w-full animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    </div>
  );
}
