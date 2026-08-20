import { createClient } from "@supabase/supabase-js";
import { browser } from "wxt/browser";

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string;
const SUPABASE_ANON = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

// Lazy: constructing eagerly runs RealtimeClient's WebSocket lookup at
// import time, which throws under plain Node (e.g. vitest) with no polyfill.
let _supabase: ReturnType<typeof createClient> | undefined;
function getSupabase() {
  if (!_supabase) {
    _supabase = createClient(SUPABASE_URL, SUPABASE_ANON, {
      auth: { persistSession: false },
    });
  }
  return _supabase;
}

const EXPIRY_SKEW_S = 60;
const APP_BASE = (import.meta.env.VITE_APP_BASE as string) ?? "http://localhost:3000";

async function persistSession(jwt: string, refresh_token: string, email: string): Promise<void> {
  await browser.storage.local.set({ jwt, refresh_token: refresh_token ?? "", email });
}

// Firefox has no externally_connectable: the user just signs in on the site and
// otclick-sync.content.ts adopts the cookie session from that tab.
export function openWebSignIn(): void {
  void browser.tabs.create({ url: `${APP_BASE}/auth` });
}

// Verify a session handed back from the web tab and persist it. Returns the
// signed-in email. Throws if the tokens don't resolve to a valid session.
export async function persistExternalSession(
  access_token: string,
  refresh_token: string,
): Promise<string> {
  if (!access_token || !refresh_token) throw new Error("tokens missing");
  const { data, error } = await getSupabase().auth.setSession({ access_token, refresh_token });
  if (error || !data.user) throw error ?? new Error("session invalid");
  const email = data.user.email ?? "";
  await persistSession(access_token, refresh_token, email);
  return email;
}

export async function signOut(): Promise<void> {
  await browser.storage.local.remove(["jwt", "refresh_token", "email"]);
}

// wxt/browser types storage reads as {}, so every read is narrowed here.
type StoredAuth = { jwt?: string; refresh_token?: string; email?: string };

const readStored = async (keys: string | string[]): Promise<StoredAuth> =>
  (await browser.storage.local.get(keys)) as StoredAuth;

export async function getJwt(): Promise<string | null> {
  const { jwt } = await readStored("jwt");
  return jwt ?? null;
}

export async function getValidJwt(): Promise<string | null> {
  const { jwt, refresh_token } = await readStored(["jwt", "refresh_token"]);
  if (!jwt) return null;
  if (!isExpiringSoon(jwt)) return jwt;
  if (!refresh_token) {
    await signOut();
    return null;
  }
  try {
    const { data, error } = await getSupabase().auth.setSession({ access_token: jwt, refresh_token });
    if (error || !data.session) {
      await signOut();
      return null;
    }
    const { email } = await readStored("email");
    await persistSession(data.session.access_token, data.session.refresh_token, email ?? "");
    return data.session.access_token;
  } catch {
    await signOut();
    return null;
  }
}

export function isExpiringSoon(jwt: string, skewS: number = EXPIRY_SKEW_S): boolean {
  try {
    const payload = JSON.parse(atob(jwt.split(".")[1]));
    return Date.now() / 1000 > payload.exp - skewS;
  } catch {
    return true;
  }
}
