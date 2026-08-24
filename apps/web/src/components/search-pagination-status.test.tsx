import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { useLinkStatus } = vi.hoisted(() => ({ useLinkStatus: vi.fn() }));

vi.mock("next/link", () => ({ useLinkStatus }));

const { SearchPaginationStatus } = await import("./search-pagination-status");

describe("SearchPaginationStatus", () => {
  it("renders an empty status region while the link is not pending", () => {
    useLinkStatus.mockReturnValue({ pending: false });

    render(<SearchPaginationStatus label="Searching for more results…" />);

    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("shows the label while the link navigation is pending", () => {
    useLinkStatus.mockReturnValue({ pending: true });

    render(<SearchPaginationStatus label="Searching for more results…" />);

    expect(screen.getByRole("status")).toHaveTextContent("Searching for more results…");
  });
});
