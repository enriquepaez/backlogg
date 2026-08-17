import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (key: string) => key,
}));

const { AdminComingSoon } = await import("./admin-coming-soon");

describe("AdminComingSoon", () => {
  it("renders the given section heading and the coming-soon copy", async () => {
    render(await AdminComingSoon({ section: "Movies" }));

    expect(screen.getByRole("heading", { name: "Movies" })).toBeInTheDocument();
    expect(screen.getByText("comingSoon")).toBeInTheDocument();
  });
});
