import { AdminUsersDirectoryPanel } from "@/components/admin-users-directory-panel";

/**
 * `/admin/users` (FE-33): the user directory table, split out of `/admin`
 * itself (Overview) into its own route reachable from `<AdminSidebar>`. The
 * auth+`is_admin` gate lives in `@/app/[locale]/admin/layout.tsx`, which
 * wraps every route under `/admin/*` — nothing left to check here.
 *
 * All the actual fetch/filter/pagination logic lives in
 * `AdminUsersDirectoryPanel` (`@/components/admin-users-directory-panel.tsx`,
 * rewritten by this same feature to a read-only `<table>` — ban/unban and
 * grant/revoke-admin now live on `/admin/users/{username}`'s own actions
 * panel instead of inline per row here).
 */
export default function AdminUsersPage() {
  return <AdminUsersDirectoryPanel />;
}
