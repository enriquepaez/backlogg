import { act } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "@/test/msw/server";

// Same rationale as `admin-reports-panel.test.tsx` for mocking `next-intl`:
// only this component's own branching (filters/loading/error/loaded/rows) is
// under test, not the translated copy itself. Interpolated keys
// (`t(key, vars)`) serialize as `key:{"var":"value"}` so assertions can match
// on both the key and the values passed to it.
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, vars?: Record<string, unknown>) =>
      vars ? `${key}:${JSON.stringify(vars)}` : key,
  useLocale: () => "en",
}));

const push = vi.fn();
vi.mock("@/i18n/navigation", () => ({
  Link: ({
    href,
    children,
    ...props
  }: {
    href: string | object;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : JSON.stringify(href)} {...props}>
      {children}
    </a>
  ),
  useRouter: () => ({ push }),
}));

const { AdminUsersDirectoryPanel } = await import("./admin-users-directory-panel");

const alice = {
  username: "alice",
  display_name: "Alice A.",
  avatar_url: null,
  is_admin: false,
  is_superadmin: false,
  is_banned: false,
  created_at: "2026-05-25T02:03:12Z",
};

const troll = {
  username: "troll",
  display_name: null,
  avatar_url: null,
  is_admin: false,
  is_superadmin: false,
  is_banned: true,
  created_at: "2026-05-20T02:03:12Z",
};

const root = {
  username: "root",
  display_name: "Root",
  avatar_url: null,
  is_admin: true,
  is_superadmin: true,
  is_banned: false,
  created_at: "2026-05-01T02:03:12Z",
};

function usersHandler(items: unknown[], overrides: Record<string, unknown> = {}) {
  return http.get("/api/admin/users", () =>
    HttpResponse.json({ items, total: items.length, page: 1, limit: 20, ...overrides }),
  );
}

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
  push.mockClear();
});

describe("AdminUsersDirectoryPanel — loading/empty/error", () => {
  it("shows a loading state before the fetch resolves", () => {
    server.use(usersHandler([]));

    render(<AdminUsersDirectoryPanel />);

    expect(screen.getByRole("status")).toHaveTextContent("loading");
  });

  it("shows an empty state when there are no users", async () => {
    server.use(usersHandler([]));

    render(<AdminUsersDirectoryPanel />);

    expect(await screen.findByText("empty")).toBeInTheDocument();
  });

  it("shows a clear, distinct message on 401 (wrong/missing key)", async () => {
    server.use(http.get("/api/admin/users", () => new HttpResponse(null, { status: 401 })));

    render(<AdminUsersDirectoryPanel />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("errors.unauthorized"));
  });

  it("shows a clear, distinct message on 503 (key not configured)", async () => {
    server.use(http.get("/api/admin/users", () => new HttpResponse(null, { status: 503 })));

    render(<AdminUsersDirectoryPanel />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("errors.not_configured"),
    );
  });

  it("shows a generic error message on an unexpected failure", async () => {
    server.use(http.get("/api/admin/users", () => new HttpResponse(null, { status: 500 })));

    render(<AdminUsersDirectoryPanel />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("errors.unknown"));
  });
});

describe("AdminUsersDirectoryPanel — table rows", () => {
  it("renders a real <table> with username, display name, joined date and no role/ban badges for a plain user", async () => {
    server.use(usersHandler([alice]));

    render(<AdminUsersDirectoryPanel />);

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Alice A." })).toHaveAttribute(
      "href",
      "/admin/users/alice",
    );
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("May 25, 2026")).toBeInTheDocument();
    expect(screen.queryByText("badges.admin")).not.toBeInTheDocument();
    expect(screen.queryByText("badges.superadmin")).not.toBeInTheDocument();
    expect(screen.queryByText("badges.banned")).not.toBeInTheDocument();
  });

  it("renders the banned badge for a banned user", async () => {
    server.use(usersHandler([troll]));

    render(<AdminUsersDirectoryPanel />);

    expect(await screen.findByText("badges.banned")).toBeInTheDocument();
  });

  it("renders the superadmin badge (not the plain admin badge) for a superadmin row", async () => {
    server.use(usersHandler([root]));

    render(<AdminUsersDirectoryPanel />);

    expect(await screen.findByText("badges.superadmin")).toBeInTheDocument();
    expect(screen.queryByText("badges.admin")).not.toBeInTheDocument();
  });

  it("renders no inline ban/unban or grant/revoke-admin actions", async () => {
    server.use(usersHandler([alice, root, troll]));

    render(<AdminUsersDirectoryPanel />);

    await screen.findByText("Alice A.");
    expect(screen.queryByRole("button", { name: /ban/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /admin/i })).not.toBeInTheDocument();
  });

  it("navigates to the user's detail page when the row is clicked", async () => {
    server.use(usersHandler([alice]));

    render(<AdminUsersDirectoryPanel />);
    const row = (await screen.findByText("@alice")).closest("tr");
    expect(row).not.toBeNull();

    await act(async () => {
      fireEvent.click(row!);
    });

    expect(push).toHaveBeenCalledWith("/admin/users/alice");
  });
});

// Radix's `Select` trigger opens on click as long as no prior `pointerdown`
// marked the interaction as mouse-originated (`pointerTypeRef` defaults to
// `"touch"` — see `@radix-ui/react-select`'s `SelectTrigger`/`SelectItem`,
// both of which call their `handleOpen`/`handleSelect` from `onClick` unless
// `pointerTypeRef.current === "mouse"`), so a plain `fireEvent.click` opens
// the trigger and selects an item without needing to fake pointer capture.
async function selectOption(triggerId: string, optionName: string) {
  await act(async () => {
    fireEvent.click(document.getElementById(triggerId)!);
  });
  await act(async () => {
    fireEvent.click(await screen.findByRole("option", { name: optionName }));
  });
}

describe("AdminUsersDirectoryPanel — filters", () => {
  it("shows a visible label above each select, not just an aria-label", () => {
    server.use(usersHandler([alice]));

    render(<AdminUsersDirectoryPanel />);

    expect(screen.getByText("filters.banned.label")).toBeInTheDocument();
    expect(screen.getByText("filters.admin.label")).toBeInTheDocument();
    expect(screen.getByText("filters.search.label")).toBeInTheDocument();
  });

  it("filters by ban status: selecting an option forwards ?is_banned= and refetches", async () => {
    let forwardedIsBanned: string | null = "not-called";
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedIsBanned = new URL(request.url).searchParams.get("is_banned");
        return HttpResponse.json({ items: [alice], total: 1, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");
    expect(forwardedIsBanned).toBeNull();

    await selectOption("users-directory-banned-filter", "filters.banned.banned");

    await waitFor(() => expect(forwardedIsBanned).toBe("true"));
  });

  it("filters by admin role: selecting an option forwards ?is_admin= and refetches", async () => {
    let forwardedIsAdmin: string | null = "not-called";
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedIsAdmin = new URL(request.url).searchParams.get("is_admin");
        return HttpResponse.json({ items: [alice], total: 1, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");
    expect(forwardedIsAdmin).toBeNull();

    await selectOption("users-directory-admin-filter", "filters.admin.notAdmin");

    await waitFor(() => expect(forwardedIsAdmin).toBe("false"));
  });

  it("combines both select filters independently in the same request", async () => {
    let forwardedParams: URLSearchParams | null = null;
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedParams = new URL(request.url).searchParams;
        return HttpResponse.json({ items: [alice], total: 1, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");

    await selectOption("users-directory-banned-filter", "filters.banned.notBanned");
    await waitFor(() => expect(forwardedParams?.get("is_banned")).toBe("false"));

    await selectOption("users-directory-admin-filter", "filters.admin.admin");

    await waitFor(() => {
      expect(forwardedParams?.get("is_banned")).toBe("false");
      expect(forwardedParams?.get("is_admin")).toBe("true");
    });
  });

  it("resets the page to 1 when a select filter changes", async () => {
    let forwardedPage: string | null = null;
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedPage = new URL(request.url).searchParams.get("page");
        return HttpResponse.json({ items: [alice], total: 41, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "pagination.next" }));
    });
    await waitFor(() => expect(forwardedPage).toBe("2"));

    await selectOption("users-directory-banned-filter", "filters.banned.banned");

    await waitFor(() => expect(forwardedPage).toBe("1"));
  });
});

describe("AdminUsersDirectoryPanel — search", () => {
  it("debounces typing: does not refetch until the user stops typing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let requestCount = 0;
    server.use(
      http.get("/api/admin/users", () => {
        requestCount += 1;
        return HttpResponse.json({ items: [alice], total: 1, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await vi.waitFor(() => expect(requestCount).toBe(1));

    const input = screen.getByPlaceholderText("filters.search.placeholder");
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.change(input, { target: { value: "al" } });
    fireEvent.change(input, { target: { value: "ali" } });

    // Still within the debounce window: no extra fetch yet.
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    expect(requestCount).toBe(1);

    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    await vi.waitFor(() => expect(requestCount).toBe(2));

    vi.useRealTimers();
  });

  it("forwards the trimmed, debounced search term and refetches", async () => {
    let forwardedSearch: string | null = "not-called";
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedSearch = new URL(request.url).searchParams.get("search");
        return HttpResponse.json({ items: [alice], total: 1, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");
    expect(forwardedSearch).toBeNull();

    fireEvent.change(screen.getByPlaceholderText("filters.search.placeholder"), {
      target: { value: "  alice  " },
    });

    await waitFor(() => expect(forwardedSearch).toBe("alice"), { timeout: 2000 });
  });

  it("omits the search param once the field is cleared back to empty", async () => {
    let forwardedHasSearch = false;
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedHasSearch = new URL(request.url).searchParams.has("search");
        return HttpResponse.json({ items: [alice], total: 1, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");

    const input = screen.getByPlaceholderText("filters.search.placeholder");
    fireEvent.change(input, { target: { value: "alice" } });
    await waitFor(() => expect(forwardedHasSearch).toBe(true), { timeout: 2000 });

    fireEvent.change(input, { target: { value: "" } });
    await waitFor(() => expect(forwardedHasSearch).toBe(false), { timeout: 2000 });
  });

  it("resets the page to 1 once the debounced search term changes", async () => {
    let forwardedPage: string | null = null;
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedPage = new URL(request.url).searchParams.get("page");
        return HttpResponse.json({ items: [alice], total: 41, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "pagination.next" }));
    });
    await waitFor(() => expect(forwardedPage).toBe("2"));

    fireEvent.change(screen.getByPlaceholderText("filters.search.placeholder"), {
      target: { value: "alice" },
    });

    await waitFor(() => expect(forwardedPage).toBe("1"), { timeout: 2000 });
  });

  it("combines search with the select filters in the same request", async () => {
    let forwardedParams: URLSearchParams | null = null;
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedParams = new URL(request.url).searchParams;
        return HttpResponse.json({ items: [alice], total: 1, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");

    await selectOption("users-directory-banned-filter", "filters.banned.notBanned");
    await waitFor(() => expect(forwardedParams?.get("is_banned")).toBe("false"));

    fireEvent.change(screen.getByPlaceholderText("filters.search.placeholder"), {
      target: { value: "alice" },
    });

    await waitFor(
      () => {
        expect(forwardedParams?.get("is_banned")).toBe("false");
        expect(forwardedParams?.get("search")).toBe("alice");
      },
      { timeout: 2000 },
    );
  });
});

describe("AdminUsersDirectoryPanel — results count", () => {
  it("shows how many users are on the current page out of the total once loaded", async () => {
    server.use(usersHandler([alice, root], { total: 41 }));

    render(<AdminUsersDirectoryPanel />);

    expect(
      await screen.findByText('resultsCount:{"shown":2,"total":41}'),
    ).toBeInTheDocument();
  });

  it("does not show a results count while still loading or on error", async () => {
    server.use(http.get("/api/admin/users", () => new HttpResponse(null, { status: 500 })));

    render(<AdminUsersDirectoryPanel />);

    expect(screen.queryByText(/^resultsCount:/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/^resultsCount:/)).not.toBeInTheDocument();
  });

  it("reflects a shorter last page's item count against the same total", async () => {
    server.use(usersHandler([alice], { total: 21, page: 2 }));

    render(<AdminUsersDirectoryPanel />);

    expect(
      await screen.findByText('resultsCount:{"shown":1,"total":21}'),
    ).toBeInTheDocument();
  });
});

describe("AdminUsersDirectoryPanel — pagination", () => {
  it("paginates: next/previous forward the right ?page= to the BFF route", async () => {
    let forwardedPage: string | null = null;
    server.use(
      http.get("/api/admin/users", ({ request }) => {
        forwardedPage = new URL(request.url).searchParams.get("page");
        return HttpResponse.json({ items: [alice], total: 41, page: 1, limit: 20 });
      }),
    );

    render(<AdminUsersDirectoryPanel />);
    await screen.findByText("Alice A.");
    expect(forwardedPage).toBe("1");

    const nextButton = screen.getByRole("button", { name: "pagination.next" });
    await act(async () => {
      fireEvent.click(nextButton);
    });

    await waitFor(() => expect(forwardedPage).toBe("2"));
  });
});
