"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

const options = [
  { value: "light", label: "Light", icon: Sun },
  { value: "system", label: "System", icon: Monitor },
  { value: "dark", label: "Dark", icon: Moon },
] as const;

export function ModeToggle() {
  // `theme` is `undefined` on the server and on the first client render, so no
  // option is marked active until next-themes resolves the value after mount.
  // This keeps server and client markup identical and avoids hydration errors.
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="group"
      aria-label="Theme"
      className="inline-flex items-center gap-1 rounded-lg border border-border p-1"
    >
      {options.map(({ value, label, icon: Icon }) => {
        const active = theme === value;
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
