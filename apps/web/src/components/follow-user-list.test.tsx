import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `catalog-card.test.tsx`.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, ...props }: React.ComponentProps<"a">) => <a href={href} {...props} />,
}));

const { FollowUserList } = await import("./follow-user-list");

const bob = { username: "bob", display_name: "Bob", avatar_url: null };
const alice = { username: "alice", display_name: null, avatar_url: "https://example.com/alice.png" };

describe("FollowUserList", () => {
  it("renders each user's display name and @username, linking to their profile", () => {
    render(<FollowUserList users={[bob]} />);

    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("@bob")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Bob/ })).toHaveAttribute("href", "/u/bob");
  });

  it("falls back to username and initials when display_name/avatar are missing", () => {
    render(<FollowUserList users={[{ username: "carol", display_name: null, avatar_url: null }]} />);

    expect(screen.getByText("carol")).toBeInTheDocument();
    expect(screen.getByText("@carol")).toBeInTheDocument();
    expect(screen.getByText("CA")).toBeInTheDocument();
  });

  it("shows an avatar image instead of initials when avatar_url is set", () => {
    const { container } = render(<FollowUserList users={[alice]} />);

    expect(container.querySelector("img")).toHaveAttribute("src", "https://example.com/alice.png");
  });

  it("renders one row per user", () => {
    render(<FollowUserList users={[bob, alice]} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
});
