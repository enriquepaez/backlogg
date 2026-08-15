"use client";

import { useTranslations } from "next-intl";

import { DeleteListDialog } from "@/components/delete-list-dialog";
import { EditListDialog } from "@/components/edit-list-dialog";
import { Card, CardContent } from "@/components/ui/card";

import type { components } from "@backlogg/api-client";

type UserListSummary = components["schemas"]["UserListSummary"];

export type UserListCardProps = {
  list: UserListSummary;
  isOwner: boolean;
};

/**
 * One list summary card for the profile page's lists grid (FE-21 read-only
 * display, FE-25 owner controls). A Client Component — unlike the plain
 * server function it replaces (`ProfileListCard`, `page.tsx`) — because
 * `EditListDialog`/`DeleteListDialog` need interactivity. `isOwner` gates
 * whether those controls render at all, same pattern as
 * `DeleteAccountDialog`/`AccountProfileForm` only ever rendering on the
 * viewer's own `/settings`; a non-owner only ever sees this card for a
 * *public* list in the first place (`getUserLists`'s doc comment,
 * `src/lib/user-content.ts`), so the visibility badge below is only shown to
 * the owner — it would be redundant noise otherwise.
 *
 * No link to a list detail page — that page doesn't exist yet (FE-26 owns
 * `GET /v1/lists/{slug}`'s page, `frontend_feature_list.json`).
 */
export function UserListCard({ list, isOwner }: UserListCardProps) {
  const t = useTranslations("Profile.lists");

  return (
    <Card>
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium">{list.title}</p>
          {isOwner ? (
            <div className="flex shrink-0 items-center gap-1">
              <EditListDialog list={list} />
              <DeleteListDialog slug={list.slug} title={list.title} />
            </div>
          ) : null}
        </div>

        {list.description ? (
          <p className="line-clamp-2 text-sm text-muted-foreground">{list.description}</p>
        ) : null}

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{t("itemCount", { count: list.item_count })}</span>
          {isOwner ? (
            <span>{list.is_public ? t("visibilityPublic") : t("visibilityPrivate")}</span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
