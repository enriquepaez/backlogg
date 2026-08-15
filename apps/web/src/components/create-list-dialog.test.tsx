import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `account-profile-form.test.tsx`/`delete-account-dialog.test.tsx`
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

const { CreateListDialog } = await import("./create-list-dialog");

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

describe("CreateListDialog", () => {
  it("does not render the form dialog before the trigger is clicked", () => {
    render(<CreateListDialog />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens with empty title/description and public checked by default", async () => {
    render(<CreateListDialog />);

    openDialog();

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("titleLabel")).toHaveValue("");
    expect(screen.getByLabelText("descriptionLabel")).toHaveValue("");
    expect(screen.getByLabelText("isPublicLabel")).toBeChecked();
  });

  it("shows a field error and never hits the network for an empty title", async () => {
    const postCall = vi.fn();
    server.use(
      http.post("/api/lists", () => {
        postCall();
        return HttpResponse.json({}, { status: 201 });
      }),
    );

    render(<CreateListDialog />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("title")).toBeInTheDocument();
    expect(postCall).not.toHaveBeenCalled();
  });

  it("submits title/description/is_public, translating a blank description to null", async () => {
    let forwardedBody: unknown;
    server.use(
      http.post("/api/lists", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json(
          {
            slug: "best-sci-fi",
            title: "Best sci-fi",
            description: null,
            is_public: true,
            item_count: 0,
            created_at: "2026-05-20T10:00:00Z",
            updated_at: "2026-05-20T10:00:00Z",
            items: [],
          },
          { status: 201 },
        );
      }),
    );

    render(<CreateListDialog />);
    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("titleLabel"), { target: { value: "Best sci-fi" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    await waitFor(() =>
      expect(forwardedBody).toEqual({ title: "Best sci-fi", description: null, is_public: true }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("success");
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows an unauthorized message on a 401 without a toast", async () => {
    server.use(http.post("/api/lists", () => new HttpResponse(null, { status: 401 })));

    render(<CreateListDialog />);
    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("titleLabel"), { target: { value: "Best sci-fi" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("unauthorized")).toBeInTheDocument();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("shows a generic error on an unexpected backend failure", async () => {
    server.use(http.post("/api/lists", () => new HttpResponse(null, { status: 500 })));

    render(<CreateListDialog />);
    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("titleLabel"), { target: { value: "Best sci-fi" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("unknown")).toBeInTheDocument();
  });
});
