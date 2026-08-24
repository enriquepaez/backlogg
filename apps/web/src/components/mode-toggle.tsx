"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun, SunMoon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import {
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";

const options = [
  { value: "light", label: "Light", icon: Sun },
  { value: "system", label: "System", icon: Monitor },
  { value: "dark", label: "Dark", icon: Moon },
] as const;

const noopSubscribe = () => () => {};

export function ModeToggle() {
  // next-themes reads the persisted theme from `localStorage` synchronously
  // inside a `useState` lazy initializer, which runs during the client's
  // first (hydration) render — not in a post-mount effect. The server has no
  // access to `localStorage` and always renders off `defaultTheme`. So if a
  // theme other than the default was previously persisted, `theme` already
  // differs between the server-rendered markup and the client's first render
  // pass, causing a hydration mismatch. `useSyncExternalStore`'s server
  // snapshot always reports `false` (matching the server-rendered markup),
  // while the client snapshot reports `true` from its first render onward —
  // this is React's recommended way to model a value that legitimately
  // differs between server and client without a setState-in-effect cascade.
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );

  return (
    <div
      role="group"
      aria-label="Theme"
      className="inline-flex items-center gap-1 rounded-lg border border-border p-1"
    >
      {options.map(({ value, label, icon: Icon }) => {
        const active = mounted && theme === value;
        return (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={active ? "secondary" : "ghost"}
            aria-pressed={active}
            onClick={() => setTheme(value)}
          >
            <Icon />
            {label}
          </Button>
        );
      })}
    </div>
  );
}

/**
 * Dropdown-menu variant of `ModeToggle`, for FE-55 "navbar decluttering":
 * nested inside a parent `DropdownMenu` (`UserNav`'s when there is a
 * session, `GuestSettingsMenu`'s otherwise) instead of its own
 * always-visible row of buttons — see `LanguageMenuItem`'s doc comment
 * (`language-switcher.tsx`) for the same rationale, which this mirrors.
 * `ModeToggle` itself is untouched and keeps its existing standalone usage
 * (`/showcase`'s kitchen sink).
 *
 * Unlike `ModeToggle`, this doesn't need the `mounted`/`useSyncExternalStore`
 * hydration guard: `DropdownMenuSubContent` (like `DropdownMenuContent`) is
 * only mounted into the DOM once the menu is opened, which can only happen
 * after hydration — there is no server-rendered markup for `theme` to
 * mismatch against here.
 */
export function ThemeMenuItem() {
  const t = useTranslations("ThemeMenu");
  const { theme, setTheme } = useTheme();

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <SunMoon aria-hidden="true" />
        {t("label")}
      </DropdownMenuSubTrigger>
      <DropdownMenuPortal>
        <DropdownMenuSubContent>
          <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme}>
            {options.map(({ value, icon: Icon }) => (
              <DropdownMenuRadioItem key={value} value={value}>
                <Icon aria-hidden="true" />
                {t(value)}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuSubContent>
      </DropdownMenuPortal>
    </DropdownMenuSub>
  );
}
