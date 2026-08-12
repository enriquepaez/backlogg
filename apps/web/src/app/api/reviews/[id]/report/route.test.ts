// @vitest-environment node
//
// Same rationale as `src/app/api/users/me/route.test.ts`: `apiFetch`
// depends on `next/headers`' request-scoped `cookies()`, so it's mocked
// here rather than exercised for real.
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api-fetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

vi.mock("@/lib/auth/session", () => ({
  authHeader: (accessToken: string | undefined) =>
    accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
}));

const { POST } = await import("./route");

function backendResponse(status: number): Response {
  return new Response(null, { status });
}

function params(id: string) {
  return { params: Promise.resolve({ id }) };
}

function reportRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/reviews/2/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function emptyRequest(): Request {
  return new Request("http://localhost:3000/api/reviews/2/report", { method: "POST" });
}

beforeEach(() => {
  apiFetchMock.mockClear();
});

const report = { id: 9, reporter_id: 1, rating_id: 2, reason: "Spam", status: "open", created_at: "t", resolved_at: null };

describe("POST /api/reviews/{id}/report", () => {
  it.each(["not-a-number", "-1", "1.5", ""])("returns 400 for an invalid id %p", async (id) => {
    const response = await POST(reportRequest({}), params(id));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 for malformed JSON", async () => {
    const request = new Request("http://x", { method: "POST", body: "not json" });
    const response = await POST(request, params("2"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("returns 400 when reason is present but not a string", async () => {
    const response = await POST(reportRequest({ reason: 42 }), params("2"));

    expect(response.status).toBe(400);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("accepts a bare POST with no body at all (optional body, docs/api.md)", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: { ...report, reason: null }, response: backendResponse(201) });

    const response = await POST(emptyRequest(), params("2"));
    const body = await response.json();

    expect(response.status).toBe(201);
    expect(body).toEqual({ id: report.id, created: true });
  });

  it("returns 201 with created:true for a brand-new report", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: report, response: backendResponse(201) });

    const response = await POST(reportRequest({ reason: "Spam" }), params("2"));
    const body = await response.json();

    expect(response.status).toBe(201);
    expect(body).toEqual({ id: report.id, created: true });
  });

  it("returns 200 with created:false for an idempotent repeat report", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: report, response: backendResponse(200) });

    const response = await POST(reportRequest({ reason: "Spam again" }), params("2"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ id: report.id, created: false });
  });

  it("forwards rating_id and reason to the typed client", async () => {
    apiFetchMock.mockImplementationOnce(
      async (call: (client: unknown, token: string | undefined) => unknown) => {
        const backendPost = vi.fn().mockResolvedValue({ data: report, response: backendResponse(201) });
        const fakeClient = { POST: backendPost };

        const result = await call(fakeClient, "the-token");

        expect(backendPost).toHaveBeenCalledWith("/v1/reviews/{rating_id}/report", {
          params: { path: { rating_id: 2 } },
          body: { reason: "Spam" },
          headers: { Authorization: "Bearer the-token" },
        });
        return result;
      },
    );

    const response = await POST(reportRequest({ reason: "Spam" }), params("2"));
    expect(response.status).toBe(201);
  });

  it("returns 401 when there is no valid session", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(401) });

    const response = await POST(reportRequest({}), params("2"));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "unauthorized" });
  });

  it("returns 404 when the review doesn't exist", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(404) });

    const response = await POST(reportRequest({}), params("999999"));
    const body = await response.json();

    expect(response.status).toBe(404);
    expect(body).toEqual({ error: "not_found" });
  });

  it("collapses any other backend status to a generic failure with the same status code", async () => {
    apiFetchMock.mockResolvedValueOnce({ response: backendResponse(500) });

    const response = await POST(reportRequest({}), params("2"));
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body).toEqual({ error: "report_failed" });
  });
});
