import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Same rationale as `follow-widget.test.tsx`: `UserListCard` mounts
// `EditListDialog`/`DeleteListDialog`, which themselves need `next-intl` and
// `@/i18n/navigation` mocked (react-hook-form/router hooks), and `sonner`
// since both dialogs import `toast` at module scope.
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const { UserListCard } = await import("./user-list-card");

const publicList = {
  slug: "best-sci-fi",
  title: "Best sci-fi",
  description: "My favorite science fiction across media.",
  is_public: true,
  item_count: 12,
  created_at: "2026-05-20T10:00:00Z",
  updated_at: "2026-05-25T18:04:11Z",
};

describe("UserListCard", () => {
  it("renders the title, description and item count for a non-owner viewer", () => {
    render(<UserListCard list={publicList} isOwner={false} />);

    expect(screen.getByText("Best sci-fi")).toBeInTheDocument();
    expect(screen.getByText("My favorite science fiction across media.")).toBeInTheDocument();
    expect(screen.getByText("itemCount")).toBeInTheDocument();
  });

  it("omits edit/delete controls and the visibility badge for a non-owner viewer", () => {
    render(<UserListCard list={publicList} isOwner={false} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("visibilityPublic")).not.toBeInTheDocument();
  });

  it("renders edit/delete controls and the visibility badge for the owner", () => {
    render(<UserListCard list={publicList} isOwner />);

    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.getByText("visibilityPublic")).toBeInTheDocument();
  });

  it("shows the private badge for a private list owned by the viewer", () => {
    render(<UserListCard list={{ ...publicList, is_public: false }} isOwner />);

    expect(screen.getByText("visibilityPrivate")).toBeInTheDocument();
  });

  it("omits the description paragraph when the list has none", () => {
    render(<UserListCard list={{ ...publicList, description: null }} isOwner={false} />);

    expect(screen.queryByText(publicList.description)).not.toBeInTheDocument();
  });
});
