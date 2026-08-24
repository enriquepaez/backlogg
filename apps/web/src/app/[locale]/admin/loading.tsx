/**
 * Route-level loading UI for `/admin` (FE-52, production audit3
 * 2026-08-24), shown by Next while `AdminLayout`'s own server-side gate
 * (`getCurrentUser`) resolves during a navigation to this segment — until
 * now this fell back to the app shell's generic spinner
 * (`[locale]/loading.tsx`). `AdminLayout` (which persists across
 * navigations within `/admin/*`) already renders `<AdminSidebar>` and the
 * `mx-auto max-w-6xl` shell around `{children}`, so this skeleton only
 * covers this page's own content: the heading and the `AdminStatsPanel`
 * (FE-28) / `AdminReportsPanel` (FE-29) sections, same pattern as
 * `browse/[type]/loading.tsx` (FE-9).
 */
export default function AdminOverviewLoading() {
  return (
    <div role="status" className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <div className="h-8 w-48 animate-pulse rounded-md bg-muted" />
        <div className="h-4 w-72 animate-pulse rounded-md bg-muted" />
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="h-24 w-full animate-pulse rounded-xl bg-muted" />
        ))}
      </div>

      <div className="flex flex-col gap-4">
        <div className="h-7 w-40 animate-pulse rounded-md bg-muted" />
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index} className="h-28 w-full animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    </div>
  );
}
