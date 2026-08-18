"use client";

import { useEffect, useState } from "react";
import { Bell, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

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
import { notificationHref, type NotificationItem } from "@/lib/notifications-types";
import { cn } from "@/lib/utils";

/** Dropdown page size — small enough for a header widget, matches `GET /api/notifications`'s own default (`src/app/api/notifications/route.ts`). */
const PAGE_LIMIT = 10;

type ListState = "idle" | "loading" | "loaded" | "error";

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
 */
export function NotificationBell() {
  const t = useTranslations("Notifications");
  const locale = useLocale();

  const [unreadCount, setUnreadCount] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [listState, setListState] = useState<ListState>("idle");
  const [items, setItems] = useState<NotificationItem[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function loadUnreadCount() {
      try {
        const response = await fetch("/api/notifications/unread_count");
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const data = (await response.json()) as { unread_count: number };
        if (!cancelled) {
          setUnreadCount(data.unread_count);
        }
      } catch (error) {
        if (cancelled) return;
        console.error("NotificationBell: failed to load the unread count", error);
      }
    }

    void loadUnreadCount();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      return;
    }

    setListState("loading");
    try {
      const response = await fetch(`/api/notifications?page=1&limit=${PAGE_LIMIT}`);
      if (!response.ok) {
        throw new Error(`unexpected status ${response.status}`);
      }
      const data = (await response.json()) as { items: NotificationItem[] };
      // The backend has no `is_read` filter on `GET /v1/notifications` (out
      // of scope to add one — see `progress/current.md`), so already-read
      // notifications are dropped client-side: the dropdown should only ever
      // show what's still unread.
      setItems(data.items.filter((item) => !item.is_read));
      setListState("loaded");
    } catch (error) {
      console.error("NotificationBell: failed to load notifications", error);
      setListState("error");
    }
  }

  async function handleDelete(id: number) {
    // Optimistic-ish: fire the delete first, but only update local state on
    // success — a failed delete leaves the row in place rather than lying
    // about what the backend actually did.
    try {
      const response = await fetch(`/api/notifications/${id}`, { method: "DELETE" });
      if (response.status !== 204) {
        throw new Error(`unexpected status ${response.status}`);
      }
      // Every item currently rendered is unread (the list is filtered
      // client-side to unread-only on load — see `handleOpenChange`), so
      // deleting any visible row is always exactly one fewer unread
      // notification, with no ambiguity about whether it was already read.
      setItems((prev) => prev.filter((item) => item.id !== id));
      setUnreadCount((prev) => (prev ? prev - 1 : 0));
    } catch (error) {
      console.error("NotificationBell: failed to delete notification", error);
    }
  }

  async function handleMarkAllRead(event: Event) {
    // Keep the dropdown open so the user sees the list clear and the badge
    // reset, instead of Radix's default "close on select" behavior.
    event.preventDefault();
    try {
      const response = await fetch("/api/notifications/read", { method: "POST" });
      if (response.status !== 204) {
        throw new Error(`unexpected status ${response.status}`);
      }
      // The endpoint marks ALL of the caller's unread notifications (no
      // `ids` sent) and the list only ever contains unread items, so a
      // successful call means everything currently shown just became read —
      // no need to refetch.
      setItems([]);
      setUnreadCount(0);
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
      {item.actor.avatar_url ? (
        // Avatar hosts aren't configured in next/image's remotePatterns yet
        // (catalog-image scope, later features) — same rationale as
        // `FeedEntryAuthor` in `feed-entry-list.tsx`.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={item.actor.avatar_url} alt="" className="mt-0.5 size-6 shrink-0 rounded-full object-cover" />
      ) : (
        <span
          aria-hidden="true"
          className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs"
        >
          {(item.actor.display_name ?? item.actor.username).slice(0, 2).toUpperCase()}
        </span>
      )}
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
