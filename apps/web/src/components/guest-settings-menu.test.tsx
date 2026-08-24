import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

// `GuestSettingsMenu` (FE-55) embeds `LanguageMenuItem`/`ThemeMenuItem`
// exactly like `UserNav` does — their own behavior is covered by
// `language-switcher.test.tsx`/`mode-toggle.test.tsx`, out of scope here,
// same rationale as `user-nav.test.tsx` mocking the same two modules.
vi.mock("@/components/language-switcher", () => ({
  LanguageMenuItem: () => <div data-testid="language-menu-item" />,
}));

vi.mock("@/components/mode-toggle", () => ({
  ThemeMenuItem: () => <div data-testid="theme-menu-item" />,
}));

const { GuestSettingsMenu } = await import("./guest-settings-menu");

// Radix's `DropdownMenuTrigger` opens on `pointerdown` (mouse button 0), not
// `click` — see `user-nav.test.tsx`'s `openMenu()` for the same note.
function openMenu() {
  fireEvent.pointerDown(screen.getByRole("button", { name: "settings" }), {
    button: 0,
    ctrlKey: false,
  });
}

describe("GuestSettingsMenu", () => {
  it("renders a compact icon trigger, closed by default", () => {
    render(<GuestSettingsMenu />);

    expect(screen.getByRole("button", { name: "settings" })).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens on trigger click and shows the language/theme entries", async () => {
    render(<GuestSettingsMenu />);

    openMenu();

    expect(await screen.findByTestId("language-menu-item")).toBeInTheDocument();
    expect(screen.getByTestId("theme-menu-item")).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    render(<GuestSettingsMenu />);

    openMenu();
    const menu = await screen.findByRole("menu");

    fireEvent.keyDown(menu, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });
});
