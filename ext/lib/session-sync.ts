// Reads the Supabase session that @supabase/ssr stores in the web app's cookies
// so the extension can auto-adopt it whenever the user is signed in on otclick.org
// (no popup "Sign in" needed). Content scripts share the page's non-httpOnly
// cookies, and @supabase/ssr's auth-token cookie is client-readable.

const SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL as string) ?? "";

// Project ref is the first label of the Supabase host: <ref>.supabase.co
function projectRef(): string | null {
  try {
    return new URL(SUPABASE_URL).hostname.split(".")[0] || null;
  } catch {
    return null;
  }
}

function b64DecodeUtf8(s: string): string {
  const norm = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(norm);
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

// @supabase/ssr stores the session JSON in `sb-<ref>-auth-token`, chunked across
// `.0`, `.1`, … when large. Reassemble the chunks in order, then decode.
function readRawCookieValue(base: string): string | null {
  const jar = new Map<string, string>();
  for (const part of document.cookie.split(";")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    const name = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    if (name === base || name.startsWith(base + ".")) jar.set(name, value);
  }
  if (jar.size === 0) return null;
  if (jar.has(base) && jar.size === 1) return decodeURIComponent(jar.get(base)!);
  const chunks: string[] = [];
  for (let i = 0; jar.has(`${base}.${i}`); i++) {
    chunks.push(jar.get(`${base}.${i}`)!);
  }
  if (chunks.length === 0) return null;
  return decodeURIComponent(chunks.join(""));
}

export interface SessionTokens {
  access_token: string;
  refresh_token: string;
}

export function readSupabaseSession(): SessionTokens | null {
  const ref = projectRef();
  if (!ref) return null;
  const raw = readRawCookieValue(`sb-${ref}-auth-token`);
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
