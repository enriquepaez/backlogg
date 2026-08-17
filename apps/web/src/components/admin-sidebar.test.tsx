import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same key-echoing mock as `admin-reports-panel.test.tsx` for `next-intl`.
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

let mockPathname = "/admin";
vi.mock("@/i18n/navigation", () => ({
  Link: ({
    href,
    children,
    ...props
  }: {
    href: string | object;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : JSON.stringify(href)} {...props}>
      {children}
    </a>
  ),
  usePathname: () => mockPathname,
}));

const { AdminSidebar } = await import("./admin-sidebar");

describe("AdminSidebar", () => {
  it("renders a link for every section", () => {
    render(<AdminSidebar />);

    expect(screen.getByRole("link", { name: "overview" })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("link", { name: "users" })).toHaveAttribute("href", "/admin/users");
    expect(screen.getByRole("link", { name: "movies" })).toHaveAttribute("href", "/admin/movies");
    expect(screen.getByRole("link", { name: "series" })).toHaveAttribute("href", "/admin/series");
    expect(screen.getByRole("link", { name: "books" })).toHaveAttribute("href", "/admin/books");
    expect(screen.getByRole("link", { name: "games" })).toHaveAttribute("href", "/admin/games");
  });

  it("marks Overview as the current page only on the exact /admin path", () => {
    mockPathname = "/admin";
    render(<AdminSidebar />);

    expect(screen.getByRole("link", { name: "overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "users" })).not.toHaveAttribute("aria-current");
  });

  it("does not mark Overview active on a nested admin route, since /admin is a prefix of it", () => {
    mockPathname = "/admin/users";
    render(<AdminSidebar />);

    expect(screen.getByRole("link", { name: "overview" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "users" })).toHaveAttribute("aria-current", "page");
  });

  it("marks Users active on a user detail route nested under /admin/users", () => {
    mockPathname = "/admin/users/alice";
    render(<AdminSidebar />);

    expect(screen.getByRole("link", { name: "users" })).toHaveAttribute("aria-current", "page");
  });
});
