import type { components } from "@backlogg/api-client";

import { Link } from "@/i18n/navigation";

type FollowUser = components["schemas"]["FollowUserOut"];

export type FollowUserListProps = {
  users: FollowUser[];
};

/**
 * Rows of `FollowUserOut` (`/u/{username}/followers`, `/u/{username}/following`
 * — FE-23), each linking to that user's public profile. Plain server-rendered
 * list, same avatar-or-initials fallback as `ReviewAuthor` (`item-reviews.tsx`)
 * and `ProfileHeader` (`page.tsx`), duplicated rather than shared — same
 * "different requirements at each call site" rationale `ReviewAuthor`'s own
 * doc comment already applies (this one has no score/date row alongside it).
 */
export function FollowUserList({ users }: FollowUserListProps) {
  return (
    <ul className="flex flex-col gap-3">
      {users.map((user) => {
        const name = user.display_name ?? user.username;
        return (
          <li key={user.username}>
            <Link
              href={`/u/${user.username}`}
              className="flex items-center gap-3 rounded-lg border border-border p-3 hover:bg-muted/50"
            >
              {user.avatar_url ? (
                // Avatar hosts aren't configured in next/image's remotePatterns yet
                // (catalog-image scope, later features) — same rationale as
                // `ReviewAuthor` in `item-reviews.tsx`.
                // eslint-disable-next-line @next/next/no-img-element
                <img src={user.avatar_url} alt="" className="size-10 rounded-full object-cover" />
              ) : (
                <span
                  aria-hidden="true"
                  className="flex size-10 items-center justify-center rounded-full bg-muted text-sm font-medium"
                >
                  {name.slice(0, 2).toUpperCase()}
                </span>
              )}
              <div className="flex flex-col">
                <span className="text-sm font-medium">{name}</span>
                <span className="text-xs text-muted-foreground">@{user.username}</span>
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
