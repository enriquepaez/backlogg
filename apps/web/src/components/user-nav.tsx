import { LogoutButton } from "@/components/logout-button";

/**
 * Minimal, client-safe subset of `UserMeOut` — deliberately excludes `email`
 * and `email_verified`. Passing the full DTO from the Server Component down
 * to this (client-rendered) component would ship those fields to the
 * browser for no reason (see `node_modules/next/dist/docs/01-app/02-guides/data-security.md`,
 * "Component-level data access": pass only what the UI needs).
 */
export type NavUser = {
  username: string;
  displayName: string | null;
  avatarUrl: string | null;
};

function initials(user: NavUser): string {
  const source = user.displayName ?? user.username;
  return source.slice(0, 2).toUpperCase();
}

export function UserNav({ user }: { user: NavUser }) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex items-center gap-2 text-sm font-medium">
        {user.avatarUrl ? (
          // Avatar hosts aren't configured in `next/image`'s remotePatterns
          // yet (catalog-image scope, later features); a plain <img> avoids
          // that dependency for now.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={user.avatarUrl}
            alt=""
            className="size-6 rounded-full object-cover"
          />
        ) : (
          <span
            aria-hidden="true"
            className="flex size-6 items-center justify-center rounded-full bg-muted text-xs"
          >
            {initials(user)}
          </span>
        )}
        <span className="max-w-32 truncate">
          {user.displayName ?? user.username}
        </span>
      </span>
      <LogoutButton />
    </div>
  );
}
