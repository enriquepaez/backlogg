"use client";

import { useEffect, useState } from "react";
import { Bell, CheckCircle2, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Image from "next/image";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Link } from "@/i18n/navigation";
import { formatDate } from "@/lib/format-date";
import { STATUS_COLOR_CLASSES } from "@/lib/library-types";
import { notificationHref, type NotificationItem } from "@/lib/notifications-types";
import { queryKeys } from "@/lib/queries/query-keys";
import { cn } from "@/lib/utils";

/** Dropdown page size — small enough for a header widget, matches `GET /api/notifications`'s own default (`src/app/api/notifications/route.ts`). */
const PAGE_LIMIT = 10;

type ListState = "idle" | "loading" | "loaded" | "error";

type UnreadCountResponse = { unread_count: number };
type NotificationsListResponse = { items: NotificationItem[] };
type DeleteNotificationResult = { status: "deleted" } | { status: "failed" };
type MarkAllReadResult = { status: "ok" } | { status: "failed" };

async function fetchUnreadCount(): Promise<UnreadCountResponse> {
  const response = await fetch("/api/notifications/unread_count");
  if (!response.ok) {
    throw new Error(`unexpected status ${response.status}`);
  }
  return (await response.json()) as UnreadCountResponse;
}

async function fetchNotificationsList(page: number, limit: number): Promise<NotificationsListResponse> {
  const response = await fetch(`/api/notifications?page=${page}&limit=${limit}`);
  if (!response.ok) {
    throw new Error(`unexpected status ${response.status}`);
  }
  return (await response.json()) as NotificationsListResponse;
}

async function deleteNotificationRequest(id: number): Promise<DeleteNotificationResult> {
  const response = await fetch(`/api/notifications/${id}`, { method: "DELETE" });
  return response.status === 204 ? { status: "deleted" } : { status: "failed" };
}

async function markAllReadRequest(): Promise<MarkAllReadResult> {
  const response = await fetch("/api/notifications/read", { method: "POST" });
  return response.status === 204 ? { status: "ok" } : { status: "failed" };
}

/**
 * Session-aware header entry point (FE-24): bell icon + unread badge, with a
 * dropdown listing the caller's most recent notifications. A Client
 * Component (unlike `FeedEntryList`/`FeedPagination`) because the badge
 * count needs to update live as the dropdown opens — same "needs its own
 * client state" rationale as `FollowWidget`'s doc comment. It can't import
 * `@/lib/notifications` itself (transitively `server-only`, via
 * `./api-fetch.ts`), so — like `FollowWidget` talking to
 * `/api/users/{username}/follow` — it talks to the BFF routes under
 * `src/app/api/notifications/` instead.
 *
 * Only ever rendered for a signed-in user (`site-header.tsx` gates it the
 * same way it gates the `/feed` nav link, via `navUser`), so unlike
 * `FollowWidget` there is no "anonymous" phase to handle here.
 *
 * Mark-as-read decision (FE-24 acceptance: "POST /v1/notifications/read
 * marca leídas y refresca el badge"; revised post-FE-24 QA — see
 * `progress/current.md`'s "Refinamiento fuera de backlog" — the original
 * version marked everything as read automatically on every dropdown open,
 * which real usage showed clears the badge before the user has actually
 * seen anything): opening the dropdown only fetches and displays the
 * caller's unread notifications (client-side filtered — the backend has no
 * `is_read` query param, see `notification-bell.test.tsx`/`docs/api.md`),
 * it no longer marks anything as read by itself. Marking as read is now an
 * explicit action: the "mark all as read" row (only shown while
 * `unreadCount > 0`) calls `POST /api/notifications/read` on click. Since
 * that endpoint marks *all* of the caller's unread notifications in one
 * call (no `ids` sent), and the list already only contains unread items,
 * a successful call means the whole visible list just became read — so the
 * list is cleared and the badge reset to 0 locally, without a refetch. The
 * list itself is still refetched on every open (not cached across opens) so
 * a notification that arrived since the last open is picked up without
 * needing a polling interval, which is out of scope here.
 *
 * FE-48: the unread-count load and the dropdown's list load both run through
 * TanStack Query's `useQuery`. `unreadCount`/`listState`/`items` are derived
 * straight from the two queries (plus `open`) on every render rather than
 * mirrored into their own state via a `useEffect` — that pattern trips
 * `react-hooks/set-state-in-effect`, since a `useQuery` result is already
 * reactive state (see `RatingWidget`'s doc comment for the same reasoning
 * spelled out in more depth). `handleDelete`/`handleMarkAllRead` write their
 * result straight into the query cache (`queryClient.setQueryData`), which
 * is what the derived values re-read on the next render.
 *
 * The list query stays keyed to `page=1`/`PAGE_LIMIT` (`queryKeys.
 * notifications.list`) but with an explicit `staleTime: 0` override (unlike
 * every other query this feature adds, which relies on the app-wide 60s
 * default, `query-provider.tsx`) — the doc comment above is explicit that
 * the list must refetch fresh "on every open, not cached across opens",
 * which a shared 60s `staleTime` would silently violate on a second open
 * within that window. `enabled: open` ties the fetch to the dropdown's own
 * open state instead of firing on mount like the unread-count query does.
 */
export function NotificationBell() {
  const t = useTranslations("Notifications");
  const locale = useLocale();
  const queryClient = useQueryClient();

  const [open, setOpen] = useState(false);

  const unreadCountQuery = useQuery({
    queryKey: queryKeys.notifications.unreadCount,
    queryFn: fetchUnreadCount,
  });
  const listKey = queryKeys.notifications.list(1, PAGE_LIMIT);
  const listQuery = useQuery({
    queryKey: listKey,
    queryFn: () => fetchNotificationsList(1, PAGE_LIMIT),
    enabled: open,
    staleTime: 0,
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteNotificationRequest(id),
  });
  const markAllReadMutation = useMutation({
    mutationFn: markAllReadRequest,
  });

  const unreadCount = unreadCountQuery.data?.unread_count ?? null;

  // Only meaningful while the dropdown is actually open — same as the
  // original `handleOpenChange`, which only ever touched `listState`/`items`
  // on the `next === true` branch. `isFetching` (not `isPending`) drives the
  // "loading" branch: after the very first open, `listQuery` already has
  // cached data, so `isPending` alone would stay `false` on a second open
  // even while the `staleTime: 0` background refetch (see this component's
  // doc comment) is still in flight.
  let listState: ListState;
  if (!open) {
    listState = "idle";
  } else if (listQuery.isFetching) {
    listState = "loading";
  } else if (listQuery.isError) {
    listState = "error";
  } else {
    listState = "loaded";
  }
  // The backend has no `is_read` filter on `GET /v1/notifications` (out of
  // scope to add one — see `progress/current.md`), so already-read
  // notifications are dropped client-side: the dropdown should only ever
  // show what's still unread.
  const items = open && listQuery.data ? listQuery.data.items.filter((item) => !item.is_read) : [];

  // Logging-only — no `setState`, so this doesn't trip
  // `react-hooks/set-state-in-effect` (`listState`/`unreadCount` above
  // already derive their own error/idle states, synchronously, every
  // render).
  useEffect(() => {
    if (unreadCountQuery.isError) {
      console.error("NotificationBell: failed to load the unread count", unreadCountQuery.error);
    }
  }, [unreadCountQuery.isError, unreadCountQuery.error]);
  useEffect(() => {
    if (open && listQuery.isError) {
      console.error("NotificationBell: failed to load notifications", listQuery.error);
    }
  }, [open, listQuery.isError, listQuery.error]);

  function handleOpenChange(next: boolean) {
    setOpen(next);
  }

  async function handleDelete(id: number) {
    // Optimistic-ish: fire the delete first, but only update the cache on
    // success — a failed delete leaves the row in place rather than lying
    // about what the backend actually did.
    try {
      const result = await deleteMutation.mutateAsync(id);
      if (result.status !== "deleted") {
        throw new Error("delete failed");
      }
      const currentList = queryClient.getQueryData<NotificationsListResponse>(listKey);
      if (currentList) {
        queryClient.setQueryData(listKey, {
          items: currentList.items.filter((item) => item.id !== id),
        } satisfies NotificationsListResponse);
      }
      // Every item currently rendered is unread (the list is filtered
      // client-side to unread-only above), so deleting any visible row is
      // always exactly one fewer unread notification, with no ambiguity
      // about whether it was already read.
      const currentUnread = queryClient.getQueryData<UnreadCountResponse>(
        queryKeys.notifications.unreadCount,
      );
      queryClient.setQueryData(queryKeys.notifications.unreadCount, {
        unread_count: currentUnread ? Math.max(0, currentUnread.unread_count - 1) : 0,
      } satisfies UnreadCountResponse);
    } catch (error) {
      console.error("NotificationBell: failed to delete notification", error);
    }
  }

  async function handleMarkAllRead(event: Event) {
    // Keep the dropdown open so the user sees the list clear and the badge
    // reset, instead of Radix's default "close on select" behavior.
    event.preventDefault();
    try {
      const result = await markAllReadMutation.mutateAsync();
      if (result.status !== "ok") {
        throw new Error("mark-all-read failed");
      }
      // The endpoint marks ALL of the caller's unread notifications (no
      // `ids` sent) and the list only ever contains unread items, so a
      // successful call means everything currently shown just became read —
      // no need to refetch.
      queryClient.setQueryData(listKey, { items: [] } satisfies NotificationsListResponse);
      queryClient.setQueryData(queryKeys.notifications.unreadCount, {
        unread_count: 0,
      } satisfies UnreadCountResponse);
    } catch (error) {
      console.error("NotificationBell: failed to mark notifications read", error);
    }
  }

  return (
    <DropdownMenu open={open} onOpenChange={handleOpenChange}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={unreadCount ? t("bellLabelUnread", { count: unreadCount }) : t("bellLabel")}
          className="relative flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        >
          <Bell aria-hidden="true" className="size-5" />
          {unreadCount ? (
            // `--destructive-foreground` doesn't exist in globals.css (only
            // `--destructive` does — confirmed no other component in the repo
            // uses that class, see `progress/current.md`'s "Refinamiento
            // fuera de backlog" for the diagnosis). Rather than adding a new
            // global design token for a single local usage, this uses an
            // explicit color per theme, picked for contrast against
            // `bg-destructive`'s two actual values: white passes AA (~4.8:1)
            // against light mode's `--destructive` but not dark mode's
            // lighter/desaturated red (~2.9:1), so dark mode swaps to a near-
            // black text (~7.3:1) instead — verified visually in both themes
            // with Playwright.
            <span
              aria-hidden="true"
              className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] leading-none font-medium text-white dark:text-neutral-950"
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          ) : null}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>{t("heading")}</DropdownMenuLabel>
        {unreadCount ? (
          <DropdownMenuItem onSelect={handleMarkAllRead}>{t("markAllRead")}</DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        {listState === "loading" || listState === "idle" ? (
          <p className="px-2 py-4 text-center text-sm text-muted-foreground">{t("loading")}</p>
        ) : listState === "error" ? (
          <p role="alert" className="px-2 py-4 text-center text-sm text-destructive">
            {t("error")}
          </p>
        ) : items.length === 0 ? (
          <p className="px-2 py-4 text-center text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <ul className="flex max-h-96 flex-col gap-1 overflow-y-auto">
            {items.map((item) => (
              <NotificationRow key={item.id} item={item} locale={locale} t={t} onDelete={handleDelete} />
            ))}
          </ul>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

type NotificationTranslator = ReturnType<typeof useTranslations<"Notifications">>;

function notificationMessage(item: NotificationItem, t: NotificationTranslator): string {
  const name = item.actor.display_name ?? item.actor.username;
  if (item.type === "new_follower") {
    return t("newFollower", { name });
  }
  if (item.type === "review_like") {
    return t("reviewLike", { name });
  }
  if (item.type === "user_completed") {
    return t("userCompleted", { name });
  }
  return t("generic", { name });
}

function NotificationRow({
  item,
  locale,
  t,
  onDelete,
}: {
  item: NotificationItem;
  locale: string;
  t: NotificationTranslator;
  onDelete: (id: number) => void;
}) {
  const href = notificationHref(item);
  const message = notificationMessage(item, t);

  const content = (
    <div className="flex items-start gap-2">
      <div className="relative mt-0.5 shrink-0">
        {item.actor.avatar_url ? (
          <Image
            src={item.actor.avatar_url}
            alt=""
            width={24}
            height={24}
            className="size-6 rounded-full object-cover"
          />
        ) : (
          <span
            aria-hidden="true"
            className="flex size-6 items-center justify-center rounded-full bg-muted text-xs"
          >
            {(item.actor.display_name ?? item.actor.username).slice(0, 2).toUpperCase()}
          </span>
        )}
        {item.type === "user_completed" ? (
          // Own icon for `user_completed` (FE-42 acceptance), layered on the
          // actor's avatar rather than replacing it — the message text still
          // needs to say *who* completed something, so the avatar stays; this
          // is purely the extra visual cue that distinguishes the type at a
          // glance, same `STATUS_COLOR_CLASSES.completed` color (and
          // `CheckCircle2` icon) `FeedEntryCompletedBadge`
          // (`feed-entry-list.tsx`) uses for the same event, for consistency
          // between the two surfaces.
          <span
            aria-hidden="true"
            className={cn(
              "absolute -right-1 -bottom-1 flex size-3.5 items-center justify-center rounded-full ring-2 ring-background",
              STATUS_COLOR_CLASSES.completed,
            )}
          >
            <CheckCircle2 className="size-2.5" />
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-0.5">
        <p
          className={cn(
            "text-sm group-hover:text-accent-foreground",
            item.is_read ? "text-muted-foreground" : "font-medium text-foreground"
          )}
        >
          {message}
        </p>
        <p className="text-xs text-muted-foreground group-hover:text-accent-foreground">
          {formatDate(item.created_at, locale)}
        </p>
      </div>
    </div>
  );

  function handleDeleteClick(event: React.MouseEvent) {
    // The delete button lives next to (not inside) the Link/div below — see
    // this function's caller for why — but Radix still treats a click
    // anywhere inside the dropdown content as a potential "select" that
    // closes the menu; stop it here so deleting a row doesn't also collapse
    // the dropdown.
    event.preventDefault();
    event.stopPropagation();
    onDelete(item.id);
  }

  return (
    <li className="group flex items-center gap-1 rounded-md hover:bg-accent">
      {/* `content` (the `Link`, when there's a target, or a plain `div`
          otherwise) and the delete button below are siblings inside this
          flex container — never one nested inside the other. A `<button>`
          nested inside the `<Link>` would be an interactive element nested
          inside another interactive element (invalid HTML) and a click on
          the button would also trigger the Link's navigation. */}
      {href ? (
        <Link href={href} className="flex-1 p-2">
          {content}
        </Link>
      ) : (
        <div className="flex-1 p-2">{content}</div>
      )}
      <button
        type="button"
        aria-label={t("deleteAriaLabel")}
        onClick={handleDeleteClick}
        className="mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <X aria-hidden="true" className="size-3.5" />
      </button>
    </li>
  );
}
