import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const replace = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/trending",
  useRouter: () => ({ replace }),
}));

vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key,
}));

const { LanguageMenuItem } = await import("./language-switcher");

// `LanguageMenuItem` is a `DropdownMenuSub` — it only makes sense mounted
// inside a parent `DropdownMenu`, the same way `UserNav`/`GuestSettingsMenu`
// use it.
function renderInMenu() {
  render(
    <DropdownMenu>
      <DropdownMenuTrigger>Open</DropdownMenuTrigger>
      <DropdownMenuContent>
        <LanguageMenuItem />
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
  replace.mockClear();
});

describe("LanguageMenuItem", () => {
  it("lists every locale as a radio item, with the active one checked", async () => {
    renderInMenu();

    openSubmenu();

    const en = await screen.findByRole("menuitemradio", { name: "en" });
    const es = screen.getByRole("menuitemradio", { name: "es" });
    expect(en).toHaveAttribute("aria-checked", "true");
    expect(es).toHaveAttribute("aria-checked", "false");
  });

  it("selecting a locale replaces the route with that locale, same pathname", async () => {
    renderInMenu();

    openSubmenu();

    const es = await screen.findByRole("menuitemradio", { name: "es" });
    fireEvent.click(es);

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/trending", { locale: "es" }),
    );
  });
});
