import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `login-form.test.tsx` for mocking `@/i18n/navigation`
// and `next-intl`.
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

const { DeleteAccountDialog } = await import("./delete-account-dialog");

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

describe("DeleteAccountDialog", () => {
  it("does not render the confirmation dialog before the trigger is clicked", () => {
    render(<DeleteAccountDialog username="alice" />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the confirmation dialog with the destructive action disabled by default", async () => {
    render(<DeleteAccountDialog username="alice" />);

    openDialog();

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "confirmButton" })).toBeDisabled();
  });

  it("keeps the destructive action disabled while the typed confirmation doesn't match the username", async () => {
    render(<DeleteAccountDialog username="alice" />);

    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("confirmLabel"), { target: { value: "bob" } });

    expect(screen.getByRole("button", { name: "confirmButton" })).toBeDisabled();
  });

  it("enables the destructive action once the typed confirmation exactly matches the username", async () => {
    render(<DeleteAccountDialog username="alice" />);

    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("confirmLabel"), { target: { value: "alice" } });

    expect(screen.getByRole("button", { name: "confirmButton" })).not.toBeDisabled();
  });

  it("on confirm, calls DELETE /api/users/me and, on success, navigates home and refreshes", async () => {
    const deleteCall = vi.fn();
    server.use(
      http.delete("/api/users/me", () => {
        deleteCall();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(<DeleteAccountDialog username="alice" />);

    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("confirmLabel"), { target: { value: "alice" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "confirmButton" }));
    });

    await waitFor(() => expect(deleteCall).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith("/");
    expect(refresh).toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalledWith("success");
  });

  it("shows an inline error and does not navigate when the delete request fails", async () => {
    server.use(http.delete("/api/users/me", () => new HttpResponse(null, { status: 500 })));

    render(<DeleteAccountDialog username="alice" />);

    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("confirmLabel"), { target: { value: "alice" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "confirmButton" }));
    });

    expect(await screen.findByText("error")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
