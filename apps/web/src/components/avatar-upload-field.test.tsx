import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args) },
}));

const { AvatarUploadField } = await import("./avatar-upload-field");

function pngFile(name = "avatar.png", sizeBytes = 10) {
  return new File([new Uint8Array(sizeBytes)], name, { type: "image/png" });
}

beforeEach(() => {
  toastSuccess.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AvatarUploadField", () => {
  it("shows a placeholder and the chooseFile label when there is no avatar yet", () => {
    render(<AvatarUploadField avatarUrl={null} onUpdated={vi.fn()} />);

    expect(screen.getByRole("button", { name: "chooseFile" })).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "remove" })).not.toBeInTheDocument();
  });

  it("shows the current avatar and changeFile/remove actions when one is set", () => {
    const { container } = render(
      <AvatarUploadField avatarUrl="https://example.com/a.png" onUpdated={vi.fn()} />,
    );

    expect(container.querySelector("img")).toHaveAttribute("src", "https://example.com/a.png");
    expect(screen.getByRole("button", { name: "changeFile" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "remove" })).toBeInTheDocument();
  });

  it("rejects a non-image/allowed file type without uploading", async () => {
    const uploadCall = vi.fn();
    server.use(
      http.post("/api/users/me/avatar", () => {
        uploadCall();
        return HttpResponse.json({}, { status: 200 });
      }),
    );

    render(<AvatarUploadField avatarUrl={null} onUpdated={vi.fn()} />);
    const input = screen.getByLabelText("chooseFile", { selector: "input" });
    const file = new File(["not an image"], "doc.pdf", { type: "application/pdf" });

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    expect(await screen.findByText("errors.invalidType")).toBeInTheDocument();
    expect(uploadCall).not.toHaveBeenCalled();
  });

  it("rejects a file over 5MB without uploading", async () => {
    const uploadCall = vi.fn();
    server.use(
      http.post("/api/users/me/avatar", () => {
        uploadCall();
        return HttpResponse.json({}, { status: 200 });
      }),
    );

    render(<AvatarUploadField avatarUrl={null} onUpdated={vi.fn()} />);
    const input = screen.getByLabelText("chooseFile", { selector: "input" });
    const file = pngFile("big.png", 5 * 1024 * 1024 + 1);

    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    expect(await screen.findByText("errors.tooLarge")).toBeInTheDocument();
    expect(uploadCall).not.toHaveBeenCalled();
  });

  it("uploads a valid file and reports the new avatar_url back to the parent", async () => {
    server.use(
      http.post("/api/users/me/avatar", () =>
        HttpResponse.json({ avatar_url: "https://cdn.example.com/avatars/1/x.png" }, { status: 200 }),
      ),
    );

    const onUpdated = vi.fn();
    render(<AvatarUploadField avatarUrl={null} onUpdated={onUpdated} />);
    const input = screen.getByLabelText("chooseFile", { selector: "input" });

    await act(async () => {
      fireEvent.change(input, { target: { files: [pngFile()] } });
    });

    await waitFor(() =>
      expect(onUpdated).toHaveBeenCalledWith("https://cdn.example.com/avatars/1/x.png"),
    );
    expect(toastSuccess).toHaveBeenCalledWith("uploadSuccess");
  });

  it("shows an unauthorized message on a 401 upload response", async () => {
    server.use(
      http.post("/api/users/me/avatar", () => new HttpResponse(null, { status: 401 })),
    );

    render(<AvatarUploadField avatarUrl={null} onUpdated={vi.fn()} />);
    const input = screen.getByLabelText("chooseFile", { selector: "input" });

    await act(async () => {
      fireEvent.change(input, { target: { files: [pngFile()] } });
    });

    expect(await screen.findByText("unauthorized")).toBeInTheDocument();
  });

  it("shows a storage-unavailable message on a 503 upload response, distinct from the generic error", async () => {
    server.use(
      http.post("/api/users/me/avatar", () => new HttpResponse(null, { status: 503 })),
    );

    render(<AvatarUploadField avatarUrl={null} onUpdated={vi.fn()} />);
    const input = screen.getByLabelText("chooseFile", { selector: "input" });

    await act(async () => {
      fireEvent.change(input, { target: { files: [pngFile()] } });
    });

    expect(await screen.findByText("errors.unavailable")).toBeInTheDocument();
  });

  it("removes the current avatar and reports null back to the parent", async () => {
    server.use(
      http.delete("/api/users/me/avatar", () => new HttpResponse(null, { status: 204 })),
    );

    const onUpdated = vi.fn();
    render(
      <AvatarUploadField avatarUrl="https://example.com/a.png" onUpdated={onUpdated} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "remove" }));
    });

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(null));
    expect(toastSuccess).toHaveBeenCalledWith("removeSuccess");
  });

  it("shows a generic error when removing the avatar fails unexpectedly", async () => {
    server.use(
      http.delete("/api/users/me/avatar", () => new HttpResponse(null, { status: 500 })),
    );

    render(
      <AvatarUploadField avatarUrl="https://example.com/a.png" onUpdated={vi.fn()} />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "remove" }));
    });

    expect(await screen.findByText("errors.generic")).toBeInTheDocument();
  });
});
