import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ItemPlatforms } from "./item-platforms";

describe("ItemPlatforms", () => {
  it("shows the empty message when there are no platforms", () => {
    render(
      <ItemPlatforms platforms={[]} heading="Platforms" emptyMessage="No platforms available." />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Platforms" })).toBeInTheDocument();
    expect(screen.getByText("No platforms available.")).toBeInTheDocument();
  });

  it("renders one badge per platform, each carrying its family color class", () => {
    render(
      <ItemPlatforms
        heading="Platforms"
        emptyMessage="No platforms available."
        platforms={[
          { id: 1, name: "PlayStation 5", slug: "ps5" },
          { id: 2, name: "Xbox Series X|S", slug: "series-x-s" },
          { id: 3, name: "Nintendo Switch", slug: "switch" },
          { id: 4, name: "PC (Microsoft Windows)", slug: "win" },
        ]}
      />,
    );

    expect(screen.getByText("PlayStation 5")).toHaveClass("bg-platform-playstation");
    expect(screen.getByText("Xbox Series X|S")).toHaveClass("bg-platform-xbox");
    expect(screen.getByText("Nintendo Switch")).toHaveClass("bg-platform-nintendo");
    expect(screen.getByText("PC (Microsoft Windows)")).toHaveClass("bg-platform-pc");
    expect(screen.queryByText("No platforms available.")).not.toBeInTheDocument();
  });

  it("falls back to the neutral genre-pill style for an unrecognized platform, never an uncolored/broken badge", () => {
    render(
      <ItemPlatforms
        heading="Platforms"
        emptyMessage="No platforms available."
        platforms={[{ id: 5, name: "Atari 2600", slug: "atari2600" }]}
      />,
    );

    const badge = screen.getByText("Atari 2600");
    expect(badge).toHaveClass("bg-muted", "text-muted-foreground");
    expect(badge.className).not.toMatch(/bg-platform-/);
  });
});
