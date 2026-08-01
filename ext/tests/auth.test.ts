import { describe, expect, it } from "vitest";
import { isExpiringSoon } from "../lib/auth";

function jwtWithExp(secondsFromNow: number): string {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + secondsFromNow }));
  return `h.${payload}.s`;
}

describe("isExpiringSoon", () => {
  it("is false for a fresh token", () => {
    expect(isExpiringSoon(jwtWithExp(3600))).toBe(false);
  });

  it("is true inside the skew window", () => {
    expect(isExpiringSoon(jwtWithExp(30))).toBe(true);
  });

  it("is true for garbage", () => {
    expect(isExpiringSoon("not-a-jwt")).toBe(true);
  });
});
