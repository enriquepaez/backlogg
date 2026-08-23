// @vitest-environment node
//
// `getUserProfile` (`@/lib/library`) is mocked so this file only exercises
// the route's own thin passthrough (status mapping, shrinking the response
// to `{ counts }`), same rationale as `notifications/unread_count/route.test.ts`.
import { beforeEach, describe, expect, it, vi } from "vitest";

const getUserProfileMock = vi.fn();
vi.mock("@/lib/library", () => ({
  getUserProfile: (...args: unknown[]) => getUserProfileMock(...args),
}));

const { GET } = await import("./route");

function params(username: string) {
  return { params: Promise.resolve({ username }) };
}

beforeEach(() => {
  getUserProfileMock.mockClear();
});

describe("GET /api/users/{username}/library_counts", () => {
  it("returns 200 with only the counts, dropping the rest of the profile", async () => {
    getUserProfileMock.mockResolvedValueOnce({
      status: "ok",
      profile: {
        username: "alice",
        display_name: "Alice",
        bio: null,
        avatar_url: null,
        follower_count: 3,
        following_count: 1,
        library_counts: { want: 3, in_progress: 1, completed: 12, dropped: 2 },
      },
    });

    const response = await GET(new Request("http://localhost:3000/api/users/alice/library_counts"), params("alice"));
    const body = await response.json();

    expect(getUserProfileMock).toHaveBeenCalledWith("alice");
    expect(response.status).toBe(200);
    expect(body).toEqual({ counts: { want: 3, in_progress: 1, completed: 12, dropped: 2 } });
  });

  it("returns 404 when the username doesn't exist", async () => {
    getUserProfileMock.mockResolvedValueOnce({ status: "not-found" });

    const response = await GET(
      new Request("http://localhost:3000/api/users/unknown/library_counts"),
      params("unknown"),
    );
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("returns 502 when the underlying fetch fails", async () => {
    getUserProfileMock.mockResolvedValueOnce({ status: "error" });

    const response = await GET(new Request("http://localhost:3000/api/users/alice/library_counts"), params("alice"));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "get_library_counts_failed" });
  });
});
