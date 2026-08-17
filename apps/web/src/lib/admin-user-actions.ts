/**
 * Shared client-side helper for the four username-keyed admin moderation
 * actions (FE-30): ban/unban and grant-admin/revoke-admin. Each POSTs to the
 * matching BFF route under `@/app/api/admin/users/[username]/**`
 * (`ban`/`unban`/`grant-admin`/`revoke-admin`), the Route Handlers that
 * inject the shared `X-API-Key` (and, for the role actions, the caller's own
 * Bearer token) server-side — this module never sees either secret, it only
 * talks to this app's own `/api/admin/users/**` routes.
 *
 * Originally inlined twice inside `AdminModerationPanel`
 * (`admin-moderation-panel.tsx`, FE-30) — once per section
 * (`AdminUserModerationSection`'s `callAction` for ban/unban,
 * `AdminRolesSection`'s `callAction` for grant/revoke-admin), nearly
 * identical apart from the action pair and response shape. FE-33 replaces
 * that "look up a username, act on it, show the last result" panel with a
 * paginated table (`@/components/admin-users-directory-panel.tsx`) that
 * needs the exact same fetch/status-mapping logic per row, so it is
 * extracted here instead of duplicated a third time. `AdminModerationPanel`
 * itself is removed by FE-33 (see that component's replacement's doc
 * comment) — this module has a single caller today, but lives under `lib/`
 * rather than inline in that one component so a future admin surface that
 * needs the same actions (or a reintroduced username-lookup shortcut) can
 * reuse it without re-duplicating the fetch/error-mapping logic again.
 */

/** Same error reasons `AdminModerationPanel` used to derive from `response.status`, minus `missingUsername` — that one was specific to the old free-text username input, which no caller of this helper has (the directory table always acts on a known row). */
export type AdminUserActionErrorReason =
  | "not_found"
  | "forbidden"
  | "unauthorized"
  | "not_configured"
  | "unknown";

export function adminUserActionReasonFromStatus(status: number): AdminUserActionErrorReason {
  if (status === 403) return "forbidden";
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status === 503) return "not_configured";
  return "unknown";
}

export type AdminUserAction = "ban" | "unban" | "grant-admin" | "revoke-admin";

/** Response shape of `POST /api/admin/users/{username}/ban` / `/unban` (`UserModerationOut`, `docs/api.md`). */
export type UserModerationResult = { username: string; is_banned: boolean };

/** Response shape of `POST /api/admin/users/{username}/grant-admin` / `/revoke-admin` (`RoleGrantOut`, `docs/api.md`). */
export type RoleGrantResult = { username: string; is_admin: boolean };

export type AdminUserActionResult =
  | { ok: true; data: UserModerationResult | RoleGrantResult }
  | { ok: false; reason: AdminUserActionErrorReason };

/**
 * POSTs `/api/admin/users/{username}/{action}` and normalizes the result:
 * `{ ok: true, data }` on 200 (`data` is the parsed `UserModerationOut` for
 * ban/unban or `RoleGrantOut` for grant-admin/revoke-admin — the caller
 * knows which shape to expect from the `action` it passed in), otherwise
 * `{ ok: false, reason }` via `adminUserActionReasonFromStatus`. A network
 * failure (thrown fetch) also maps to `{ ok: false, reason: "unknown" }`,
 * same as the original inlined `callAction`s.
 */
export async function callAdminUserAction(
  action: AdminUserAction,
  username: string,
): Promise<AdminUserActionResult> {
  try {
    const response = await fetch(`/api/admin/users/${encodeURIComponent(username)}/${action}`, {
      method: "POST",
    });
    if (response.status === 200) {
      const data = (await response.json()) as UserModerationResult | RoleGrantResult;
      return { ok: true, data };
    }
    return { ok: false, reason: adminUserActionReasonFromStatus(response.status) };
  } catch {
    return { ok: false, reason: "unknown" };
  }
}
