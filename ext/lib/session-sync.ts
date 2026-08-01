// Reads the Supabase session that @supabase/ssr stores in the web app's cookies
// so the extension can auto-adopt it whenever the user is signed in on Otclick
// (no "Sign in" click needed). Content scripts share the page's non-httpOnly
// cookies, and @supabase/ssr's auth-token cookie is client-readable.
//
// The cookie is named `sb-<project-ref>-auth-token`, where the ref comes from
// the Supabase URL — and that differs between a hosted project and the
// self-hosted stack on localhost. Instead of deriving the ref, find whichever
// cookie matches the shape: one code path for both deployments.

function b64DecodeUtf8(s: string): string {
  const norm = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(norm);
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

const AUTH_COOKIE_RE = /^sb-.+-auth-token(\.\d+)?$/;

function parseCookieJar(cookieString: string): Map<string, string> {
  const jar = new Map<string, string>();
  for (const part of cookieString.split(";")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    jar.set(part.slice(0, eq).trim(), part.slice(eq + 1).trim());
  }
  return jar;
}

/** Reassemble the raw cookie value: large sessions are chunked across
 *  `<name>.0`, `<name>.1`, … and must be joined in order before decoding. */
function readRawValue(jar: Map<string, string>): string | null {
  const names = [...jar.keys()].filter((n) => AUTH_COOKIE_RE.test(n));
  if (names.length === 0) return null;
  const base = names[0].replace(/\.\d+$/, "");
  if (jar.has(base)) return decodeURIComponent(jar.get(base)!);
  const chunks: string[] = [];
  for (let i = 0; jar.has(`${base}.${i}`); i++) chunks.push(jar.get(`${base}.${i}`)!);
  if (chunks.length === 0) return null;
  return decodeURIComponent(chunks.join(""));
}

export interface SessionTokens {
  access_token: string;
  refresh_token: string;
}

/** Pure core, exported for tests: a cookie header string → session tokens. */
export function parseSessionFromCookies(cookieString: string): SessionTokens | null {
  const raw = readRawValue(parseCookieJar(cookieString));
  if (!raw) return null;
  try {
    const json = raw.startsWith("base64-") ? b64DecodeUtf8(raw.slice("base64-".length)) : raw;
    const parsed = JSON.parse(json);
    const session = Array.isArray(parsed) ? parsed[0] : parsed;
    const access_token = session?.access_token;
    const refresh_token = session?.refresh_token;
    if (typeof access_token === "string" && typeof refresh_token === "string") {
      return { access_token, refresh_token };
    }
  } catch {
    return null;
  }
  return null;
}

export function readSupabaseSession(): SessionTokens | null {
  return parseSessionFromCookies(document.cookie);
}
