import { describe, expect, it, vi, afterEach } from "vitest";

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { getSession: async () => ({ data: { session: null } }) },
  }),
}));

const { apiFetch, ApiError } = await import("@/lib/api");

function respond(body: string, contentType: string, status: number) {
  vi.stubGlobal("fetch", async () =>
    new Response(body, { status, headers: { "content-type": contentType } }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("не выносит HTML-страницу ошибки в текст сообщения", async () => {
    respond("<!DOCTYPE html><html><body>404</body></html>", "text/html", 404);
    await expect(apiFetch("/api/resumes")).rejects.toMatchObject({
      message: "HTTP 404",
      status: 404,
    });
  });

  it("показывает detail из JSON-ошибки", async () => {
    respond(JSON.stringify({ detail: "нет доступа" }), "application/json", 403);
    await expect(apiFetch("/api/resumes")).rejects.toThrow("нет доступа");
  });

  it("возвращает распарсенный JSON", async () => {
    respond(JSON.stringify({ items: [1] }), "application/json", 200);
    expect(await apiFetch("/api/resumes")).toEqual({ items: [1] });
  });

  it("бросает ApiError", async () => {
    respond("oops", "text/plain", 500);
    await expect(apiFetch("/api/resumes")).rejects.toBeInstanceOf(ApiError);
  });
});
