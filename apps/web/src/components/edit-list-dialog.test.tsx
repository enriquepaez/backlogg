import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `create-list-dialog.test.tsx` for mocking
// `@/i18n/navigation` and `next-intl`.
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

const { EditListDialog } = await import("./edit-list-dialog");

const list = {
  slug: "best-sci-fi",
  title: "Best sci-fi",
  description: "My favorites",
  is_public: true,
  item_count: 3,
  created_at: "2026-05-20T10:00:00Z",
  updated_at: "2026-05-25T18:04:11Z",
};

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

describe("EditListDialog", () => {
  it("does not render the form dialog before the trigger is clicked", () => {
    render(<EditListDialog list={list} />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("pre-fills the fields from the given list", async () => {
    render(<EditListDialog list={list} />);

    openDialog();

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("titleLabel")).toHaveValue("Best sci-fi");
    expect(screen.getByLabelText("descriptionLabel")).toHaveValue("My favorites");
    expect(screen.getByLabelText("isPublicLabel")).toBeChecked();
  });

  it("pre-fills an empty description and unchecked visibility for a private list with no description", async () => {
    render(<EditListDialog list={{ ...list, description: null, is_public: false }} />);

    openDialog();
    await screen.findByRole("dialog");

    expect(screen.getByLabelText("descriptionLabel")).toHaveValue("");
    expect(screen.getByLabelText("isPublicLabel")).not.toBeChecked();
  });

  it("shows a field error and never hits the network for an emptied title", async () => {
    const patchCall = vi.fn();
    server.use(
      http.patch("/api/lists/best-sci-fi", () => {
        patchCall();
        return HttpResponse.json({}, { status: 200 });
      }),
    );

    render(<EditListDialog list={list} />);
    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("titleLabel"), { target: { value: "   " } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("title")).toBeInTheDocument();
    expect(patchCall).not.toHaveBeenCalled();
  });

  it("submits title/description/is_public and, on success, closes the dialog and refreshes", async () => {
    let forwardedBody: unknown;
    server.use(
      http.patch("/api/lists/best-sci-fi", async ({ request }) => {
        forwardedBody = await request.json();
        return HttpResponse.json({ ...list, title: "Best sci-fi ever", is_public: false }, { status: 200 });
      }),
    );

    render(<EditListDialog list={list} />);
    openDialog();
    await screen.findByRole("dialog");
    fireEvent.change(screen.getByLabelText("titleLabel"), { target: { value: "Best sci-fi ever" } });
    fireEvent.click(screen.getByLabelText("isPublicLabel"));

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    await waitFor(() =>
      expect(forwardedBody).toEqual({
        title: "Best sci-fi ever",
        description: "My favorites",
        is_public: false,
      }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("success");
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a forbidden message on a 403", async () => {
    server.use(http.patch("/api/lists/best-sci-fi", () => new HttpResponse(null, { status: 403 })));

    render(<EditListDialog list={list} />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("forbidden")).toBeInTheDocument();
  });

  it("shows a not-found message on a 404", async () => {
    server.use(http.patch("/api/lists/best-sci-fi", () => new HttpResponse(null, { status: 404 })));

    render(<EditListDialog list={list} />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("notFound")).toBeInTheDocument();
  });

  it("shows an unauthorized message on a 401", async () => {
    server.use(http.patch("/api/lists/best-sci-fi", () => new HttpResponse(null, { status: 401 })));

    render(<EditListDialog list={list} />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("unauthorized")).toBeInTheDocument();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("shows a generic error on an unexpected backend failure", async () => {
    server.use(http.patch("/api/lists/best-sci-fi", () => new HttpResponse(null, { status: 500 })));

    render(<EditListDialog list={list} />);
    openDialog();
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "submit" }));
    });

    expect(await screen.findByText("unknown")).toBeInTheDocument();
  });
});
