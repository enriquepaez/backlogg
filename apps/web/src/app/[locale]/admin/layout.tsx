import { setRequestLocale } from "next-intl/server";

import { AdminSidebar } from "@/components/admin-sidebar";
import { redirect } from "@/i18n/navigation";
import { getCurrentUser } from "@/lib/api-fetch";

/**
 * Layout for the whole `/admin/*` surface (FE-33): centralizes the
 * auth+`is_admin` gate that used to live only in `/admin`'s own `page.tsx`
 * (FE-28, later hardened by the `admin_role_gate` fix bundled into that same
 * feature) so every admin route — `/admin` (Overview), `/admin/users`,
 * `/admin/users/{username}`, and the catalog stubs — is covered by the exact
 * same check, instead of each page repeating it (or, worse, one of them
 * forgetting to and silently reopening the vulnerability that fix closed).
 *
 * Same defense-in-depth rationale as before: `proxy.ts`
 * (`lib/auth/protected-routes.ts`) already redirects signed-out requests
 * away at the edge based on cookie PRESENCE only; this layout's own
 * `getCurrentUser()` call is the real, server-side session + authorization
 * check. A signed-out visitor goes to `/login`; a signed-in but non-admin
 * user goes to `/` (NOT `/login` — they *are* authenticated, just not
 * authorized for this section).
 *
 * Renders `<AdminSidebar>` (nav for Overview/Users/Movies/Series/Books/Games,
 * FE-33) beside `{children}` — every admin page below only needs to render
 * its own content, not the shell.
 *
 * Doesn't thread `user`/`isSuperadmin` down via context: `getCurrentUser()`
 * is memoized per-request with React `cache()` (see that helper's own doc
 * comment), so the one child page that actually needs `is_superadmin`
 * (`/admin/users/{username}`, for its actions panel) just calls it again
 * itself — cheap, and simpler than introducing a context provider for a
 * single consumer.
 */
export default async function AdminLayout({
  children,
  params,
}: LayoutProps<"/[locale]/admin">) {
  const { locale } = await params;
  setRequestLocale(locale);

  const user = await getCurrentUser();
  if (!user) {
    redirect({ href: "/login", locale });
    return null;
  }
  if (!user.is_admin) {
    redirect({ href: "/", locale });
    return null;
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-16 md:flex-row">
      <AdminSidebar />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
