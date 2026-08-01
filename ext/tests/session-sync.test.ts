import { describe, expect, it } from "vitest";
import { parseSessionFromCookies } from "../lib/session-sync";

const session = { access_token: "acc", refresh_token: "ref" };
const b64 = (s: string) => Buffer.from(s, "utf8").toString("base64");

describe("parseSessionFromCookies", () => {
  it("reads a plain JSON cookie from the local stack", () => {
    const raw = encodeURIComponent(JSON.stringify(session));
    expect(parseSessionFromCookies(`sb-localhost-auth-token=${raw}; other=1`)).toEqual(session);
  });

  it("reads a hosted project's base64 cookie", () => {
    const raw = encodeURIComponent("base64-" + b64(JSON.stringify(session)));
    expect(parseSessionFromCookies(`sb-abcdef-auth-token=${raw}`)).toEqual(session);
  });

  it("reassembles chunked cookies in order", () => {
    const raw = encodeURIComponent(JSON.stringify(session));
    const half = Math.floor(raw.length / 2);
    const jar = `sb-localhost-auth-token.0=${raw.slice(0, half)}; sb-localhost-auth-token.1=${raw.slice(half)}`;
    expect(parseSessionFromCookies(jar)).toEqual(session);
  });

  it("unwraps the array form supabase-ssr sometimes writes", () => {
    const raw = encodeURIComponent(JSON.stringify([session]));
    expect(parseSessionFromCookies(`sb-x-auth-token=${raw}`)).toEqual(session);
  });

  it("returns null without an auth cookie", () => {
    expect(parseSessionFromCookies("theme=dark; foo=bar")).toBeNull();
  });

  it("returns null on malformed content", () => {
    expect(parseSessionFromCookies("sb-x-auth-token=not-json")).toBeNull();
  });
});
