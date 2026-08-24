import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

/**
 * Separate file from `search-controls.test.tsx`: forces `useTransition`'s
 * `isPending` to `true` for every render here (a real transition's pending
 * window is too short-lived to reliably observe under jsdom with a mocked,
 * synchronous `router.replace` — see `SearchControls`' own comment on why
 * `useLinkStatus` doesn't apply to this component). This isolates the one
 * thing worth a regression test: that `isPending` actually drives the
 * "searching" status text, independent of exercising the real transition.
 */
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useTransition: () => [true, (callback: () => void) => callback()],
  };
});

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const { SearchControls } = await import("./search-controls");

describe("SearchControls (isPending)", () => {
  it("shows the searching status text while a navigation transition is pending", () => {
    render(<SearchControls initialQuery="dune" />);

    expect(screen.getByRole("status")).toHaveTextContent("searching");
  });
});
