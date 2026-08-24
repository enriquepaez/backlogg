"use client";

import { useLocale, useTranslations } from "next-intl";
import { Languages } from "lucide-react";

import { usePathname, useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import {
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Language switcher, rendered as a `DropdownMenuSub` meant to be nested
 * inside a parent `DropdownMenu` (FE-55 "navbar decluttering"). It used to
 * be its own always-visible row of locale buttons directly in the header —
 * user feedback was that the header has too many things visible at once, so
 * language/theme now live inside a menu instead: `UserNav`'s dropdown when
 * there is a session, `GuestSettingsMenu`'s otherwise. This keeps the
 * capability (nothing is removed, per the acceptance criteria), just moves
 * where it lives.
 *
 * A `DropdownMenuRadioGroup` (single-select — exactly one active locale at a
 * time) rather than plain `DropdownMenuItem`s: it is the Radix-idiomatic way
 * to model "pick one of N", with the checked indicator and `menuitemradio`
 * role/`aria-checked` wiring included for free instead of hand-rolled.
 */
export function LanguageMenuItem() {
  const locale = useLocale();
  const router = useRouter();
  // `usePathname` from next-intl returns the pathname without the locale
  // prefix, so switching the locale keeps the user on the same page.
  const pathname = usePathname();
  const t = useTranslations("LanguageSwitcher");

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <Languages aria-hidden="true" />
        {t("label")}
      </DropdownMenuSubTrigger>
      <DropdownMenuPortal>
        <DropdownMenuSubContent>
          <DropdownMenuRadioGroup
            value={locale}
            onValueChange={(value) =>
              router.replace(pathname, { locale: value as (typeof routing.locales)[number] })
            }
          >
            {routing.locales.map((value) => (
              <DropdownMenuRadioItem key={value} value={value}>
                {t(value)}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuSubContent>
      </DropdownMenuPortal>
    </DropdownMenuSub>
  );
}
