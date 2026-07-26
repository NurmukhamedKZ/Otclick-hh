import { describe, expect, it } from "vitest";
import { DEFAULT_VIEW, parseView, serializeView } from "./applications-url";

const parse = (qs: string) => parseView(new URLSearchParams(qs));

describe("parseView", () => {
  it("returns the default view for an empty query", () => {
    expect(parse("")).toEqual(DEFAULT_VIEW);
  });

  it("reads status, query and 1-based page into a 0-based page", () => {
    expect(parse("status=captcha&q=abc&p=3")).toEqual({ status: "captcha", q: "abc", page: 2 });
  });

  it("falls back to 'all' for an unknown status", () => {
    expect(parse("status=nonsense").status).toBe("all");
  });

  it("clamps a non-positive or non-numeric page to the first page", () => {
    expect(parse("p=0").page).toBe(0);
    expect(parse("p=-4").page).toBe(0);
    expect(parse("p=abc").page).toBe(0);
  });

  it("trims the search query", () => {
    expect(parse("q=%20%20yandex%20%20").q).toBe("yandex");
  });
});

describe("serializeView", () => {
  it("serializes the default view to an empty string", () => {
    expect(serializeView(DEFAULT_VIEW)).toBe("");
  });

  it("omits keys that are at their default", () => {
    expect(serializeView({ status: "captcha", q: "", page: 0 })).toBe("?status=captcha");
    expect(serializeView({ status: "all", q: "abc", page: 0 })).toBe("?q=abc");
    expect(serializeView({ status: "all", q: "", page: 2 })).toBe("?p=3");
  });

  it("round-trips a fully populated view", () => {
    const view = { status: "failed", q: "ozon", page: 4 };
    expect(parse(serializeView(view).slice(1))).toEqual(view);
  });
});
