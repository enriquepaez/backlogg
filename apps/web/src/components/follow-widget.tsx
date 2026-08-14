"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button, buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

export type FollowWidgetProps = {
  /** The profile being viewed — never the viewer's own (`isOwnProfile` gates the button). */
  username: string;
  initialFollowerCount: number;
  isOwnProfile: boolean;
};

type Phase = "loading" | "anonymous" | "ready";

/**
 * "Followers count + follow/unfollow button" for the public profile page
 * (FE-23), `/u/{username}`. One client component (not two) because the
 * follower count needs to update optimistically alongside the button — see
 * `ProfileHeader`'s doc comment in `page.tsx` for why `followingCount`
 * stays a plain server-rendered link instead: toggling follow on this page
 * only ever changes *this* profile's follower count, never its following
 * count.
 *
 * Same `pending`-guarded optimistic-update-with-rollback pattern as
 * `ViewerStatusSlot`/`item-reviews.tsx`'s `toggleLike`: fetches its own
 * initial state on mount (`GET /api/users/{username}/follow`) rather than a
 * prop, because the profile page stays a public, ISR-friendly Server
 * Component whose own fetch never sends cookies/Authorization.
 *
 * Skips the initial fetch entirely when `isOwnProfile` — the button never
 * renders on your own profile (self-follow is a 422 on the backend,
 * `docs/api.md`), so there's nothing to check.
 */
export function FollowWidget({ username, initialFollowerCount, isOwnProfile }: FollowWidgetProps) {
  const t = useTranslations("Profile");

  const [phase, setPhase] = useState<Phase>(isOwnProfile ? "ready" : "loading");
  const [following, setFollowing] = useState(false);
  const [followerCount, setFollowerCount] = useState(initialFollowerCount);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (isOwnProfile) return;
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch(`/api/users/${username}/follow`);
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const data = (await response.json()) as { authenticated: boolean; following: boolean };
        if (cancelled) return;

        if (!data.authenticated) {
          setPhase("anonymous");
          return;
        }
        setFollowing(data.following);
        setPhase("ready");
      } catch (error) {
        if (cancelled) return;
        console.error("FollowWidget: failed to load the viewer's follow status", error);
        setPhase("ready");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [username, isOwnProfile]);

  async function toggle() {
    if (pending) return;
    const previousFollowing = following;
    const previousCount = followerCount;
    const next = !following;

    setPending(true);
    setFollowing(next);
    setFollowerCount((count) => count + (next ? 1 : -1));

    let ok = false;
    try {
      const response = await fetch(`/api/users/${username}/follow`, {
        method: next ? "POST" : "DELETE",
      });
      ok = response.status === 204;
    } catch {
      ok = false;
    } finally {
      if (!ok) {
        setFollowing(previousFollowing);
        setFollowerCount(previousCount);
        toast.error(t("follow.error"));
      }
      setPending(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Link
        href={`/u/${username}/followers`}
        className="text-sm text-muted-foreground hover:text-foreground hover:underline"
      >
        {t("followersCount", { count: followerCount })}
      </Link>

      {isOwnProfile ? null : phase === "loading" ? (
        <Button type="button" size="sm" variant="outline" disabled>
          {t("follow.loading")}
        </Button>
      ) : phase === "anonymous" ? (
        <Link href="/login" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
          {t("follow.follow")}
        </Link>
      ) : (
        <Button
          type="button"
          size="sm"
          variant={following ? "outline" : "default"}
          aria-pressed={following}
          disabled={pending}
          onClick={toggle}
        >
          {following ? t("follow.unfollow") : t("follow.follow")}
        </Button>
      )}
    </div>
  );
}
