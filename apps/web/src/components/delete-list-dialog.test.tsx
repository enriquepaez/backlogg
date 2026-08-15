import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `delete-account-dialog.test.tsx`/`create-list-dialog.test.tsx`
// for mocking `@/i18n/navigation` and `next-intl`.
const push = vi.fn();
const refresh = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args) },
}));

const { DeleteListDialog } = await import("./delete-list-dialog");

function openDialog() {
  fireEvent.click(screen.getByRole("button", { name: "openDialog" }));
}

beforeEach(() => {
  push.mockClear();
  refresh.mockClear();
  toastSuccess.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DeleteListDialog", () => {
  it("does not render the confirmation dialog before the trigger is clicked", () => {
    render(<DeleteListDialog slug="best-sci-fi" title="Best sci-fi" />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("on confirm, calls DELETE /api/lists/{slug} and, on success, closes the dialog and refreshes", async () => {
    const deleteCall = vi.fn();
    server.use(
      http.delete("/api/lists/best-sci-fi", () => {
        deleteCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<DeleteListDialog slug="best-sci-fi" title="Best sci-fi" />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "confirmButton" }));
    });

    await waitFor(() => expect(deleteCall).toHaveBeenCalledTimes(1));
    expect(refresh).toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalledWith("success");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a forbidden error and does not refresh on a 403", async () => {
    server.use(http.delete("/api/lists/best-sci-fi", () => new HttpResponse(null, { status: 403 })));

    render(<DeleteListDialog slug="best-sci-fi" title="Best sci-fi" />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "confirmButton" }));
    });

    expect(await screen.findByText("forbidden")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("shows a not-found error on a 404", async () => {
    server.use(http.delete("/api/lists/best-sci-fi", () => new HttpResponse(null, { status: 404 })));

    render(<DeleteListDialog slug="best-sci-fi" title="Best sci-fi" />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "confirmButton" }));
    });

    expect(await screen.findByText("notFound")).toBeInTheDocument();
  });

  it("shows an unknown error on an unexpected backend failure", async () => {
    server.use(http.delete("/api/lists/best-sci-fi", () => new HttpResponse(null, { status: 500 })));

    render(<DeleteListDialog slug="best-sci-fi" title="Best sci-fi" />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "confirmButton" }));
    });

    expect(await screen.findByText("unknown")).toBeInTheDocument();
  });
});
