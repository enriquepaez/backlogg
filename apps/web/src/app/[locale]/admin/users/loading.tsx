/**
 * Route-level loading UI for `/admin/users` (FE-52, production audit3
 * 2026-08-24), shown by Next while `AdminLayout`'s own server-side gate
 * (`getCurrentUser`) resolves during a navigation to this segment — until
 * now this fell back to the app shell's generic spinner
 * (`[locale]/loading.tsx`). `AdminLayout` (which persists across
 * navigations within `/admin/*`) already renders `<AdminSidebar>` and the
 * `mx-auto max-w-6xl` shell around `{children}`, so this skeleton only
 * covers this page's own content: the heading, filter row and table that
 * `AdminUsersDirectoryPanel` (FE-33) renders once its client-side fetch
 * resolves, same pattern as `browse/[type]/loading.tsx` (FE-9).
 */
export default function AdminUsersLoading() {
  return (
    <div role="status" className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="h-7 w-32 animate-pulse rounded-md bg-muted" />
        <div className="h-4 w-64 animate-pulse rounded-md bg-muted" />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:gap-4">
        <div className="h-9 min-w-56 flex-1 animate-pulse rounded-md bg-muted" />
        <div className="h-9 w-44 animate-pulse rounded-md bg-muted" />
        <div className="h-9 w-44 animate-pulse rounded-md bg-muted" />
      </div>

      <div className="flex flex-col gap-2">
        {Array.from({ length: 8 }, (_, index) => (
          <div key={index} className="h-12 w-full animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    </div>
  );
}
