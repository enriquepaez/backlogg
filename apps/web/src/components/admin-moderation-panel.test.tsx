import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `admin-reports-panel.test.tsx` for mocking `next-intl`:
// only this component's own branching is under test, not the translated
// copy itself.
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

const { AdminModerationPanel } = await import("./admin-moderation-panel");

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
  toastSuccess.mockClear();
  toastError.mockClear();
});

function usernameInput(name: RegExp | string) {
  return screen.getByLabelText(name);
}

describe("AdminModerationPanel — user ban/unban", () => {
  it("shows a missing-username error without calling the backend", async () => {
    render(<AdminModerationPanel isSuperadmin={false} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "unbanAction" }));
    });

    expect(await screen.findByText("errors.missingUsername")).toBeInTheDocument();
  });

  it("unbans a user directly (no confirmation) and shows the resulting status", async () => {
    let calledUsername: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/unban", ({ params }) => {
        calledUsername = params.username as string;
        return HttpResponse.json({ username: "alice", is_banned: false });
      }),
    );

    render(<AdminModerationPanel isSuperadmin={false} />);
    fireEvent.change(usernameInput("usernameLabel"), { target: { value: "alice" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "unbanAction" }));
    });

    expect(calledUsername).toBe("alice");
    expect(toastSuccess).toHaveBeenCalledWith("success.unbanned");
    expect(await screen.findByText('statusNotBanned:{"username":"alice"}')).toBeInTheDocument();
  });

  it("requires confirmation before banning: opening the dialog does not call the backend", async () => {
    const banCall = vi.fn();
    server.use(
      http.post("/api/admin/users/:username/ban", () => {
        banCall();
        return HttpResponse.json({ username: "troll", is_banned: true });
      }),
    );

    render(<AdminModerationPanel isSuperadmin={false} />);
    fireEvent.change(usernameInput("usernameLabel"), { target: { value: "troll" } });

    fireEvent.click(screen.getByRole("button", { name: "banAction" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(banCall).not.toHaveBeenCalled();
  });

  it("bans a user after confirming the dialog", async () => {
    let calledUsername: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/ban", ({ params }) => {
        calledUsername = params.username as string;
        return HttpResponse.json({ username: "troll", is_banned: true });
      }),
    );

    render(<AdminModerationPanel isSuperadmin={false} />);
    fireEvent.change(usernameInput("usernameLabel"), { target: { value: "troll" } });
    fireEvent.click(screen.getByRole("button", { name: "banAction" }));
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "banDialog.confirm" }));
    });

    expect(calledUsername).toBe("troll");
    expect(toastSuccess).toHaveBeenCalledWith("success.banned");
    expect(await screen.findByText('statusBanned:{"username":"troll"}')).toBeInTheDocument();
  });

  it("maps a 404 from the ban route to a not-found error", async () => {
    server.use(
      http.post("/api/admin/users/:username/ban", () =>
        HttpResponse.json({ error: "not_found" }, { status: 404 }),
      ),
    );

    render(<AdminModerationPanel isSuperadmin={false} />);
    fireEvent.change(usernameInput("usernameLabel"), { target: { value: "ghost" } });
    fireEvent.click(screen.getByRole("button", { name: "banAction" }));
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "banDialog.confirm" }));
    });

    expect(await screen.findByText("errors.not_found")).toBeInTheDocument();
  });
});

describe("AdminModerationPanel — admin role grant/revoke", () => {
  it("is not rendered at all for a non-superadmin caller", () => {
    render(<AdminModerationPanel isSuperadmin={false} />);

    expect(screen.queryByRole("button", { name: "grantAction" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "revokeAction" })).not.toBeInTheDocument();
  });

  it("is rendered for a superadmin caller", () => {
    render(<AdminModerationPanel isSuperadmin={true} />);

    expect(screen.getByRole("button", { name: "grantAction" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "revokeAction" })).toBeInTheDocument();
  });

  it("grants admin directly (no confirmation) and shows the resulting status", async () => {
    let calledUsername: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/grant-admin", ({ params }) => {
        calledUsername = params.username as string;
        return HttpResponse.json({ username: "alice", is_admin: true });
      }),
    );

    render(<AdminModerationPanel isSuperadmin={true} />);
    const [, rolesUsernameInput] = screen.getAllByLabelText("usernameLabel");
    fireEvent.change(rolesUsernameInput, { target: { value: "alice" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "grantAction" }));
    });

    expect(calledUsername).toBe("alice");
    expect(toastSuccess).toHaveBeenCalledWith("success.granted");
    expect(await screen.findByText('statusAdmin:{"username":"alice"}')).toBeInTheDocument();
  });

  it("requires confirmation before revoking: opening the dialog does not call the backend", async () => {
    const revokeCall = vi.fn();
    server.use(
      http.post("/api/admin/users/:username/revoke-admin", () => {
        revokeCall();
        return HttpResponse.json({ username: "alice", is_admin: false });
      }),
    );

    render(<AdminModerationPanel isSuperadmin={true} />);
    const [, rolesUsernameInput] = screen.getAllByLabelText("usernameLabel");
    fireEvent.change(rolesUsernameInput, { target: { value: "alice" } });

    fireEvent.click(screen.getByRole("button", { name: "revokeAction" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(revokeCall).not.toHaveBeenCalled();
  });

  it("revokes admin after confirming the dialog", async () => {
    let calledUsername: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/revoke-admin", ({ params }) => {
        calledUsername = params.username as string;
        return HttpResponse.json({ username: "alice", is_admin: false });
      }),
    );

    render(<AdminModerationPanel isSuperadmin={true} />);
    const [, rolesUsernameInput] = screen.getAllByLabelText("usernameLabel");
    fireEvent.change(rolesUsernameInput, { target: { value: "alice" } });
    fireEvent.click(screen.getByRole("button", { name: "revokeAction" }));
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "revokeDialog.confirm" }));
    });

    expect(calledUsername).toBe("alice");
    expect(toastSuccess).toHaveBeenCalledWith("success.revoked");
    expect(await screen.findByText('statusNotAdmin:{"username":"alice"}')).toBeInTheDocument();
  });

  it("maps a 403 from the grant route to a forbidden error", async () => {
    server.use(
      http.post("/api/admin/users/:username/grant-admin", () =>
        HttpResponse.json({ error: "forbidden" }, { status: 403 }),
      ),
    );

    render(<AdminModerationPanel isSuperadmin={true} />);
    const [, rolesUsernameInput] = screen.getAllByLabelText("usernameLabel");
    fireEvent.change(rolesUsernameInput, { target: { value: "alice" } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "grantAction" }));
    });

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("errors.forbidden"));
  });
});
