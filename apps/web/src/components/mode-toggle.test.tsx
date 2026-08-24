import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const setTheme = vi.fn();

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "system", setTheme }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { ThemeMenuItem } = await import("./mode-toggle");

// `ThemeMenuItem` is a `DropdownMenuSub` — it only makes sense mounted
// inside a parent `DropdownMenu`, the same way `UserNav`/`GuestSettingsMenu`
// use it.
function renderInMenu() {
  render(
    <DropdownMenu>
      <DropdownMenuTrigger>Open</DropdownMenuTrigger>
      <DropdownMenuContent>
        <ThemeMenuItem />
      </DropdownMenuContent>
    </DropdownMenu>,
  );
}

// Radix's `DropdownMenuTrigger`/`DropdownMenuSubTrigger` open on
// `pointerdown`/`click` respectively — see `user-nav.test.tsx`'s
// `openMenu()` and `@radix-ui/react-menu`'s `MenuSubTrigger` `onClick`.
function openSubmenu() {
  fireEvent.pointerDown(screen.getByRole("button", { name: "Open" }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.click(screen.getByRole("menuitem", { name: "label" }));
}

beforeEach(() => {
  setTheme.mockClear();
});

describe("ThemeMenuItem", () => {
  it("lists light/system/dark as radio items, with the active one checked", async () => {
    renderInMenu();

    openSubmenu();

    const system = await screen.findByRole("menuitemradio", { name: "system" });
    const dark = screen.getByRole("menuitemradio", { name: "dark" });
    expect(system).toHaveAttribute("aria-checked", "true");
    expect(dark).toHaveAttribute("aria-checked", "false");
  });

  it("selecting a theme calls setTheme", async () => {
    renderInMenu();

    openSubmenu();

    const dark = await screen.findByRole("menuitemradio", { name: "dark" });
    fireEvent.click(dark);

    await waitFor(() => expect(setTheme).toHaveBeenCalledWith("dark"));
  });
});
