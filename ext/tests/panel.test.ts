import { describe, expect, it } from "vitest";
import { renderFilledList, statusText } from "../lib/panel";

describe("renderFilledList", () => {
  it("marks AI values apart from profile values", () => {
    const html = renderFilledList([
      { label: "E-mail", value: "a@b.c", source: "profile" },
      { label: "Почему вы?", value: "Потому что", source: "ai" },
    ]);
    expect(html).toContain("E-mail");
    expect(html).toContain("otc-src-ai");
    expect(html).toContain("otc-src-profile");
  });

  it("escapes user content", () => {
    const html = renderFilledList([{ label: "<img src=x onerror=1>", value: "v", source: "ai" }]);
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("shows an empty state", () => {
    expect(renderFilledList([])).toContain("Пока ничего не заполнено");
  });
});

describe("statusText", () => {
  it("tells the user they submit the form themselves", () => {
    expect(statusText("done", { filled: 4 })).toContain("4");
    expect(statusText("done", { filled: 4 })).toMatch(/отправ/i);
  });

  it("surfaces the error text", () => {
    expect(statusText("error", { error: "Войдите в аккаунт" })).toBe("Войдите в аккаунт");
  });

  it("is empty when idle", () => {
    expect(statusText("idle")).toBe("");
  });
});

describe("statusText: saved", () => {
  it("reports how many answers were remembered", () => {
    expect(statusText("saved", { filled: 2 })).toContain("2");
  });

  it("says plainly when there was nothing to save", () => {
    expect(statusText("saved", { filled: 0 })).toContain("нечего");
  });
});
