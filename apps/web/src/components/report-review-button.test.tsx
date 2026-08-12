import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `delete-account-dialog.test.tsx` for mocking
// `next-intl` and `sonner`.
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args) },
}));

const { ReportReviewButton } = await import("./report-review-button");

function openDialog() {
  fireEvent.click(screen.getByRole("button", { name: "openDialog" }));
}

beforeEach(() => {
  toastSuccess.mockClear();
});

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

describe("ReportReviewButton", () => {
  it("does not render the dialog before the trigger is clicked", () => {
    render(<ReportReviewButton ratingId={42} />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("posts to /api/reviews/{id}/report with the typed reason, then disables the trigger", async () => {
    let forwardedBody: unknown;
    server.use(
      http.post("/api/reviews/42/report", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ id: 1, created: true }, { status: 201 });
      }),
    );

    render(<ReportReviewButton ratingId={42} />);
    openDialog();
    await screen.findByRole("dialog");

    fireEvent.change(screen.getByLabelText("reasonLabel"), { target: { value: "Spam" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(forwardedBody).toEqual({ reason: "Spam" });
    expect(toastSuccess).toHaveBeenCalledWith("success");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "reported" })).toBeDisabled();
  });

  it("sends reason:null when no reason was typed", async () => {
    let forwardedBody: unknown;
    server.use(
      http.post("/api/reviews/42/report", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ id: 1, created: true }, { status: 201 });
      }),
    );

    render(<ReportReviewButton ratingId={42} />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(forwardedBody).toEqual({ reason: null });
  });

  it("treats an idempotent repeat report (200) the same as a fresh one (201)", async () => {
    server.use(
      http.post("/api/reviews/42/report", () =>
        HttpResponse.json({ id: 1, created: false }, { status: 200 }),
      ),
    );

    render(<ReportReviewButton ratingId={42} />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(toastSuccess).toHaveBeenCalledWith("success");
    expect(screen.getByRole("button", { name: "reported" })).toBeDisabled();
  });

  it("shows an inline error and keeps the dialog open when the report request fails", async () => {
    server.use(http.post("/api/reviews/42/report", () => new HttpResponse(null, { status: 500 })));

    render(<ReportReviewButton ratingId={42} />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("error")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
