import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `follow-pagination.test.tsx`.
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
}));

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
}));

// `FeedTabs` is a Server Component (async function returning JSX) — called
// directly and awaited, same pattern as `follow-pagination.test.tsx`.
const { FeedTabs } = await import("./feed-tabs");

describe("FeedTabs", () => {
  it("renders both tabs as a tablist, marking the current one selected", async () => {
    render(await FeedTabs({ tab: "following" }));

    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "following" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "popular" })).toHaveAttribute("aria-selected", "false");
  });

  it("links the following tab to /feed with no tab query param (the default)", async () => {
    render(await FeedTabs({ tab: "popular" }));

    expect(screen.getByRole("tab", { name: "following" })).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/feed", query: {} }),
    );
  });

  it("links the popular tab to /feed?tab=popular", async () => {
    render(await FeedTabs({ tab: "following" }));

    expect(screen.getByRole("tab", { name: "popular" })).toHaveAttribute(
      "href",
      JSON.stringify({ pathname: "/feed", query: { tab: "popular" } }),
    );
  });
});
