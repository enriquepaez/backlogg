import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `user-nav.test.tsx`/`site-header.test.tsx` for mocking
// `@/i18n/navigation`'s `Link`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { NavMenu } = await import("./nav-menu");

const links = [
  { href: "/trending", label: "Trending" },
  { href: "/genres", label: "Genres" },
];

// Radix's `DropdownMenuTrigger` opens on `pointerdown` (mouse button 0), not
// `click` — see `user-nav.test.tsx`'s `openMenu()` for the same note.
function openMenu(name: string) {
  fireEvent.pointerDown(screen.getByRole("button", { name }), {
    button: 0,
    ctrlKey: false,
  });
}

describe("NavMenu", () => {
  it("renders the trigger label and keeps the menu closed by default", () => {
    render(<NavMenu label="Explore" links={links} />);

    expect(screen.getByRole("button", { name: "Explore" })).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens on trigger click and shows every link with its href", async () => {
    render(<NavMenu label="Explore" links={links} />);

    openMenu("Explore");

    expect(await screen.findByRole("menuitem", { name: "Trending" })).toHaveAttribute(
      "href",
      "/trending",
    );
    expect(screen.getByRole("menuitem", { name: "Genres" })).toHaveAttribute("href", "/genres");
  });

  it("is keyboard accessible: opens on Enter and closes on Escape", async () => {
    render(<NavMenu label="Explore" links={links} />);

    const trigger = screen.getByRole("button", { name: "Explore" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });

    const menu = await screen.findByRole("menu");

    fireEvent.keyDown(menu, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  });
});
