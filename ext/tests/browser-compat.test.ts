import { describe, expect, it } from "vitest";
import { toolbarButtonApi } from "../lib/browser-compat";

describe("toolbarButtonApi", () => {
  it("prefers browserAction (Manifest V2, what we ship)", () => {
    expect(toolbarButtonApi({ browserAction: "mv2", action: "mv3" })).toBe("mv2");
  });

  it("falls back to action (Manifest V3)", () => {
    expect(toolbarButtonApi({ action: "mv3" })).toBe("mv3");
  });

  it("throws loudly instead of returning undefined", () => {
    expect(() => toolbarButtonApi({})).toThrow(/toolbar button API/);
  });
});
