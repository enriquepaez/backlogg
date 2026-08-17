import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const fetchAdminCatalogItem = vi.fn();
const saveAdminCatalogItem = vi.fn();
vi.mock("@/lib/admin-catalog", async () => {
  const actual = await vi.importActual<typeof import("@/lib/admin-catalog")>("@/lib/admin-catalog");
  return {
    ...actual,
    fetchAdminCatalogItem: (...args: unknown[]) => fetchAdminCatalogItem(...args),
    saveAdminCatalogItem: (...args: unknown[]) => saveAdminCatalogItem(...args),
  };
});

const { AdminCatalogEditDialog } = await import("./admin-catalog-edit-dialog");

const movieItem = {
  type: "movie",
  slug: "dune-2021",
  title: "Dune",
  poster_url: "https://example.com/dune.jpg",
  release_date: "2021-10-22",
  first_air_date: null,
  first_publish_date: null,
  genres: ["Science Fiction", "Adventure"],
  locked_fields: ["title"],
};

function renderDialog(overrides: Partial<Parameters<typeof AdminCatalogEditDialog>[0]> = {}) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  const utils = render(
    <AdminCatalogEditDialog
      type="movie"
      slug="dune-2021"
      fallbackTitle="Dune"
      dateLabel="Release date"
      onClose={onClose}
      onSaved={onSaved}
      {...overrides}
    />,
  );
  return { ...utils, onClose, onSaved };
}

afterEach(() => {
  fetchAdminCatalogItem.mockReset();
  saveAdminCatalogItem.mockReset();
  toastSuccess.mockClear();
  toastError.mockClear();
});

describe("AdminCatalogEditDialog — loading/error", () => {
  it("shows a loading state before the fetch resolves", () => {
    fetchAdminCatalogItem.mockReturnValue(new Promise(() => {}));

    renderDialog();

    expect(screen.getByRole("status")).toHaveTextContent("loading");
  });

  it("shows a clear error message when the fetch fails", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: false, reason: "not_found" });

    renderDialog();

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("errors.not_found"));
  });
});

describe("AdminCatalogEditDialog — loaded form", () => {
  it("prefills every field with the fetched item's current values", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });

    renderDialog();

    expect(await screen.findByDisplayValue("Dune")).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://example.com/dune.jpg")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2021-10-22")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Science Fiction, Adventure")).toBeInTheDocument();
  });

  it("shows a locked badge and unlock checkbox only for fields in locked_fields", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });

    renderDialog();
    await screen.findByDisplayValue("Dune");

    // Only "title" is locked in the fixture -> exactly one badge/checkbox.
    expect(screen.getAllByText("lockedBadge")).toHaveLength(1);
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });

  it("disables Save until something changes", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });

    renderDialog();
    await screen.findByDisplayValue("Dune");

    expect(screen.getByRole("button", { name: "save" })).toBeDisabled();
  });

  it("blocks submission and shows a field error when title is cleared to blank", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });

    renderDialog();
    const titleInput = await screen.findByDisplayValue("Dune");
    fireEvent.change(titleInput, { target: { value: "   " } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    expect(await screen.findByText("errors.title")).toBeInTheDocument();
    expect(saveAdminCatalogItem).not.toHaveBeenCalled();
  });

  it("only sends dirty fields on save, omitting untouched ones", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });
    saveAdminCatalogItem.mockResolvedValue({ ok: true, item: { ...movieItem, poster_url: "https://example.com/new.jpg" } });

    const { onSaved } = renderDialog();
    await screen.findByDisplayValue("Dune");

    fireEvent.change(screen.getByDisplayValue("https://example.com/dune.jpg"), {
      target: { value: "https://example.com/new.jpg" },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    await waitFor(() => expect(saveAdminCatalogItem).toHaveBeenCalled());
    expect(saveAdminCatalogItem).toHaveBeenCalledWith("movie", "dune-2021", {
      poster_url: "https://example.com/new.jpg",
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(toastSuccess).toHaveBeenCalledWith("success");
  });

  it("splits and trims the comma-separated genres field into an array on save", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });
    saveAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });

    renderDialog();
    await screen.findByDisplayValue("Dune");

    fireEvent.change(screen.getByDisplayValue("Science Fiction, Adventure"), {
      target: { value: "Drama,  Thriller ,Drama" },
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    await waitFor(() =>
      expect(saveAdminCatalogItem).toHaveBeenCalledWith("movie", "dune-2021", {
        genres: ["Drama", "Thriller", "Drama"],
      }),
    );
  });

  it("clearing the date field sends null, not an empty string", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });
    saveAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });

    renderDialog();
    await screen.findByDisplayValue("Dune");

    fireEvent.change(screen.getByDisplayValue("2021-10-22"), { target: { value: "" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    await waitFor(() =>
      expect(saveAdminCatalogItem).toHaveBeenCalledWith("movie", "dune-2021", { release_date: null }),
    );
  });

  it("checking 'unlock' on a locked field sends it via unlock_fields even without editing it", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });
    saveAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });

    renderDialog();
    await screen.findByDisplayValue("Dune");

    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox"));
    });
    expect(screen.getByRole("button", { name: "save" })).not.toBeDisabled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    await waitFor(() =>
      expect(saveAdminCatalogItem).toHaveBeenCalledWith("movie", "dune-2021", { unlock_fields: ["title"] }),
    );
  });

  it("shows a generic error toast when saving fails", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });
    saveAdminCatalogItem.mockResolvedValue({ ok: false, reason: "unauthorized" });

    renderDialog();
    await screen.findByDisplayValue("Dune");

    fireEvent.change(screen.getByDisplayValue("https://example.com/dune.jpg"), {
      target: { value: "https://example.com/new.jpg" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "save" }));
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("errors.unauthorized"));
  });

  it("calls onClose when Cancel is clicked", async () => {
    fetchAdminCatalogItem.mockResolvedValue({ ok: true, item: movieItem });

    const { onClose } = renderDialog();
    await screen.findByDisplayValue("Dune");

    fireEvent.click(screen.getByRole("button", { name: "cancel" }));

    expect(onClose).toHaveBeenCalled();
  });
});
