import { createBrowserClient } from "@supabase/ssr";

const ANON_KEY_COOKIE = "otclick-supabase-anon-key";
const GOOGLE_AUTH_COOKIE = "otclick-google-auth-enabled";
const SSR_PLACEHOLDER_URL = "http://localhost";
const SSR_PLACEHOLDER_KEY = "runtime-config-loaded-in-browser";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of document.cookie.split(";")) {
    const value = part.trim();
    if (!value.startsWith(prefix)) continue;
    return decodeURIComponent(value.slice(prefix.length));
  }
  return null;
}

export function isGoogleAuthEnabled(): boolean {
  return readCookie(GOOGLE_AUTH_COOKIE) === "true";
}

export function createClient() {
  // Client Components may be pre-rendered by Next.js. No browser auth request is
  // made during that render, so a non-secret placeholder keeps the build generic;
  // the browser execution below always replaces it with runtime configuration.
  if (typeof window === "undefined") {
    return createBrowserClient(SSR_PLACEHOLDER_URL, SSR_PLACEHOLDER_KEY, {
      cookieOptions: { name: "sb-otclick-auth-token" },
    });
  }

  const anonKey = readCookie(ANON_KEY_COOKIE);
  if (!anonKey) {
    throw new Error("Runtime Supabase configuration is missing; reload the page");
  }

  return createBrowserClient(window.location.origin, anonKey, {
    cookieOptions: { name: "sb-otclick-auth-token" },
  });
}
