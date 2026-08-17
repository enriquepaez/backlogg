import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `admin-users-directory-panel.test.tsx` for mocking
// `next-intl`.
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

const { AdminUserActionsPanel } = await import("./admin-user-actions-panel");

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
  toastSuccess.mockClear();
  toastError.mockClear();
});

describe("AdminUserActionsPanel — badges", () => {
  it("renders no role/ban badges for a plain, non-banned user", () => {
    render(
      <AdminUserActionsPanel
        username="alice"
        initialIsAdmin={false}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={false}
      />,
    );

    expect(screen.queryByText("badges.admin")).not.toBeInTheDocument();
    expect(screen.queryByText("badges.superadmin")).not.toBeInTheDocument();
    expect(screen.queryByText("badges.banned")).not.toBeInTheDocument();
  });

  it("renders the superadmin badge instead of the plain admin badge", () => {
    render(
      <AdminUserActionsPanel
        username="root"
        initialIsAdmin={true}
        initialIsBanned={false}
        isTargetSuperadmin={true}
        callerIsSuperadmin={false}
      />,
    );

    expect(screen.getByText("badges.superadmin")).toBeInTheDocument();
    expect(screen.queryByText("badges.admin")).not.toBeInTheDocument();
  });

  it("renders the banned badge", () => {
    render(
      <AdminUserActionsPanel
        username="troll"
        initialIsAdmin={false}
        initialIsBanned={true}
        isTargetSuperadmin={false}
        callerIsSuperadmin={false}
      />,
    );

    expect(screen.getByText("badges.banned")).toBeInTheDocument();
  });
});

describe("AdminUserActionsPanel — role actions visibility", () => {
  it("never shows grant/revoke-admin actions when the caller is not a superadmin", () => {
    render(
      <AdminUserActionsPanel
        username="alice"
        initialIsAdmin={false}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={false}
      />,
    );

    expect(screen.queryByRole("button", { name: "actions.grantAction" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "actions.revokeAction" })).not.toBeInTheDocument();
  });

  it("shows grant-admin when the caller is a superadmin and the target is not an admin", () => {
    render(
      <AdminUserActionsPanel
        username="alice"
        initialIsAdmin={false}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={true}
      />,
    );

    expect(screen.getByRole("button", { name: "actions.grantAction" })).toBeInTheDocument();
  });

  it("shows revoke-admin when the caller is a superadmin and the target is an admin", () => {
    render(
      <AdminUserActionsPanel
        username="bob"
        initialIsAdmin={true}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={true}
      />,
    );

    expect(screen.getByRole("button", { name: "actions.revokeAction" })).toBeInTheDocument();
  });
});

describe("AdminUserActionsPanel — ban/unban", () => {
  it("unbans directly (no confirmation) and patches the badge/button in place", async () => {
    let calledUsername: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/unban", ({ params }) => {
        calledUsername = params.username as string;
        return HttpResponse.json({ username: "troll", is_banned: false });
      }),
    );

    render(
      <AdminUserActionsPanel
        username="troll"
        initialIsAdmin={false}
        initialIsBanned={true}
        isTargetSuperadmin={false}
        callerIsSuperadmin={false}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "actions.unbanAction" }));
    });

    expect(calledUsername).toBe("troll");
    expect(toastSuccess).toHaveBeenCalledWith("actions.success.unbanned");
    expect(screen.queryByText("badges.banned")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "actions.banAction" })).toBeInTheDocument();
  });

  it("requires confirmation before banning: opening the dialog does not call the backend", async () => {
    const banCall = vi.fn();
    server.use(
      http.post("/api/admin/users/:username/ban", () => {
        banCall();
        return HttpResponse.json({ username: "alice", is_banned: true });
      }),
    );

    render(
      <AdminUserActionsPanel
        username="alice"
        initialIsAdmin={false}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={false}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "actions.banAction" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(banCall).not.toHaveBeenCalled();
  });

  it("bans after confirming the dialog and patches the badge/button in place", async () => {
    let calledUsername: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/ban", ({ params }) => {
        calledUsername = params.username as string;
        return HttpResponse.json({ username: "alice", is_banned: true });
      }),
    );

    render(
      <AdminUserActionsPanel
        username="alice"
        initialIsAdmin={false}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={false}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "actions.banAction" }));
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "actions.banDialog.confirm" }));
    });

    expect(calledUsername).toBe("alice");
    expect(toastSuccess).toHaveBeenCalledWith("actions.success.banned");
    expect(await screen.findByText("badges.banned")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "actions.unbanAction" })).toBeInTheDocument();
  });

  it("shows an error toast and leaves state unchanged when ban fails", async () => {
    server.use(
      http.post("/api/admin/users/:username/ban", () => new HttpResponse(null, { status: 404 })),
    );

    render(
      <AdminUserActionsPanel
        username="ghost"
        initialIsAdmin={false}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={false}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "actions.banAction" }));
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "actions.banDialog.confirm" }));
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("actions.errors.not_found"));
    expect(screen.queryByText("badges.banned")).not.toBeInTheDocument();
  });
});

describe("AdminUserActionsPanel — grant/revoke-admin", () => {
  it("grants admin directly (no confirmation) and patches the badge/button in place", async () => {
    let calledUsername: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/grant-admin", ({ params }) => {
        calledUsername = params.username as string;
        return HttpResponse.json({ username: "alice", is_admin: true });
      }),
    );

    render(
      <AdminUserActionsPanel
        username="alice"
        initialIsAdmin={false}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={true}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "actions.grantAction" }));
    });

    expect(calledUsername).toBe("alice");
    expect(toastSuccess).toHaveBeenCalledWith("actions.success.granted");
    expect(await screen.findByText("badges.admin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "actions.revokeAction" })).toBeInTheDocument();
  });

  it("requires confirmation before revoking: opening the dialog does not call the backend", async () => {
    const revokeCall = vi.fn();
    server.use(
      http.post("/api/admin/users/:username/revoke-admin", () => {
        revokeCall();
        return HttpResponse.json({ username: "bob", is_admin: false });
      }),
    );

    render(
      <AdminUserActionsPanel
        username="bob"
        initialIsAdmin={true}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={true}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "actions.revokeAction" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(revokeCall).not.toHaveBeenCalled();
  });

  it("revokes after confirming the dialog and patches the badge/button in place", async () => {
    let calledUsername: string | undefined;
    server.use(
      http.post("/api/admin/users/:username/revoke-admin", ({ params }) => {
        calledUsername = params.username as string;
        return HttpResponse.json({ username: "bob", is_admin: false });
      }),
    );

    render(
      <AdminUserActionsPanel
        username="bob"
        initialIsAdmin={true}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={true}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "actions.revokeAction" }));
    await screen.findByRole("dialog");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "actions.revokeDialog.confirm" }));
    });

    expect(calledUsername).toBe("bob");
    expect(toastSuccess).toHaveBeenCalledWith("actions.success.revoked");
    expect(screen.getByRole("button", { name: "actions.grantAction" })).toBeInTheDocument();
  });

  it("maps a 403 from the grant route to a forbidden error toast", async () => {
    server.use(
      http.post("/api/admin/users/:username/grant-admin", () =>
        HttpResponse.json({ error: "forbidden" }, { status: 403 }),
      ),
    );

    render(
      <AdminUserActionsPanel
        username="alice"
        initialIsAdmin={false}
        initialIsBanned={false}
        isTargetSuperadmin={false}
        callerIsSuperadmin={true}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "actions.grantAction" }));
    });

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("actions.errors.forbidden"));
  });
});
