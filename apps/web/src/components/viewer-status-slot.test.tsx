import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ViewerStatusSlot } from "./viewer-status-slot";

describe("ViewerStatusSlot", () => {
  it("renders nothing today (FE-14/FE-20 extension point, no session plumbing yet)", () => {
    const { container } = render(<ViewerStatusSlot status={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a non-null status either (no consumer yet)", () => {
    const { container } = render(<ViewerStatusSlot status="want" />);

    expect(container).toBeEmptyDOMElement();
  });
});
