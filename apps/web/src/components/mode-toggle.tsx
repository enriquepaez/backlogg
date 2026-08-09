"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

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
