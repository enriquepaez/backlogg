import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  it("renders its children as an accessible button", () => {
    render(<Button>Save changes</Button>);

    expect(
      screen.getByRole("button", { name: "Save changes" }),
    ).toBeInTheDocument();
  });

  it("fires onClick when clicked", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Click me</Button>);

    screen.getByRole("button", { name: "Click me" }).click();

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("exposes the variant and size as data attributes", () => {
    render(
      <Button variant="outline" size="lg">
        Cancel
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Cancel" });
    expect(button).toHaveAttribute("data-variant", "outline");
    expect(button).toHaveAttribute("data-size", "lg");
  });

  it("is disabled and unclickable when the disabled prop is set", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Disabled
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Disabled" });
    expect(button).toBeDisabled();

    button.click();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("renders as its child element when asChild is set, instead of a <button>", () => {
    // Plain external `<a>` on purpose: this only exercises `asChild`
    // composing with the child element, not in-app navigation (which would
    // go through `next/link`, per this file's own eslint rules).
    render(
      <Button asChild>
        <a href="https://example.com/docs">Read the docs</a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "Read the docs" });
    expect(link).toHaveAttribute("href", "https://example.com/docs");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
