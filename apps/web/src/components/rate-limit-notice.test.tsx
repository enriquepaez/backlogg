import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const refresh = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key,
}));

const { RateLimitNotice } = await import("./rate-limit-notice");

beforeEach(() => {
  refresh.mockClear();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RateLimitNotice", () => {
  it("counts down from retryAfterSeconds, without offering a retry action yet", () => {
    render(<RateLimitNotice retryAfterSeconds={2} />);

    expect(screen.getByText('waiting:{"seconds":2}')).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText('waiting:{"seconds":1}')).toBeInTheDocument();

    // Still no retry button, and no navigation/refresh has happened while
    // waiting — the countdown alone must never trigger a retry.
    expect(refresh).not.toHaveBeenCalled();
  });

  it("offers a manual retry action once the countdown reaches zero, and never auto-refreshes", () => {
    render(<RateLimitNotice retryAfterSeconds={1} />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();

    // Give it plenty more time — still no automatic retry.
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(refresh).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("treats a missing Retry-After (null) as immediately retryable", () => {
    render(<RateLimitNotice retryAfterSeconds={null} />);

    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "retry" })).toBeInTheDocument();
  });
});
