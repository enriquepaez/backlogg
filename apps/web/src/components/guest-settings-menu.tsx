"use client";

import { Settings } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LanguageMenuItem } from "@/components/language-switcher";
import { ThemeMenuItem } from "@/components/mode-toggle";

/**
 * Signed-out counterpart to the language/theme entries `UserNav` gains once
 * there is a session (FE-55 "navbar decluttering"). A visitor has no
 * `UserNav` to hang those off, so this is a standalone settings-only
 * dropdown — same `LanguageMenuItem`/`ThemeMenuItem` `DropdownMenuSub`
 * entries, behind a compact icon trigger next to the "log in" link.
 */
export function GuestSettingsMenu() {
  const t = useTranslations("Nav");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon-sm" aria-label={t("settings")}>
          <Settings aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{t("settings")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <LanguageMenuItem />
        <ThemeMenuItem />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
