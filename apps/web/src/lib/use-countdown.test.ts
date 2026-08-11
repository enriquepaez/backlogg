import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCountdown } from "./use-countdown";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useCountdown", () => {
  it("ticks down to zero, one second at a time", () => {
    const { result } = renderHook(({ seconds }) => useCountdown(seconds), {
      initialProps: { seconds: 2 as number | null },
    });

    expect(result.current).toBe(2);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(1);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(0);

    // Stays at zero — no negative countdown.
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(0);
  });

  it("restarts the countdown when a new seconds value is passed in", () => {
    const { result, rerender } = renderHook(({ seconds }) => useCountdown(seconds), {
      initialProps: { seconds: 1 as number | null },
    });

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(0);

    rerender({ seconds: 5 });
    expect(result.current).toBe(5);
  });

  it("treats null as an immediate zero", () => {
    const { result } = renderHook(() => useCountdown(null));
    expect(result.current).toBe(0);
  });
});
