/**
 * Route-level loading UI for `/genres` (FE-12), shown by Next while the
 * page's data fetch (`getGenrePage`) is in flight during a navigation to this
 * segment. Skeleton chip rows echo the eventual per-type sections (see
 * `page.tsx`/`GenreSections`) instead of the app shell's generic spinner
 * (`[locale]/loading.tsx`).
 */
export default function GenresLoading() {
  return (
    <div
      role="status"
      className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16"
    >
      <div className="flex flex-col gap-2">
        <div className="h-9 w-40 animate-pulse rounded-md bg-muted" />
        <div className="h-5 w-72 animate-pulse rounded-md bg-muted" />
      </div>
      <div className="h-8 w-40 animate-pulse rounded-lg bg-muted" />
      <div className="flex flex-col gap-10">
        {Array.from({ length: 2 }, (_, sectionIndex) => (
          <div key={sectionIndex} className="flex flex-col gap-4">
            <div className="h-7 w-32 animate-pulse rounded-md bg-muted" />
            <div className="flex flex-wrap gap-2">
              {Array.from({ length: 8 }, (_, chipIndex) => (
                <div
                  key={chipIndex}
                  className="h-8 w-24 animate-pulse rounded-full bg-muted"
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
