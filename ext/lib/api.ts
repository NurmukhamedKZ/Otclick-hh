import { getValidJwt } from "./auth";

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? "http://localhost:8000";

/** Authed call to the Otclick backend. Throws Error("unauthorized") when the
 *  stored session is gone or rejected, so callers can show the sign-in prompt
 *  instead of a generic failure. */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const jwt = await getValidJwt();
  if (!jwt) throw new Error("unauthorized");
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
      Authorization: `Bearer ${jwt}`,
    },
  });
  if (resp.status === 401) throw new Error("unauthorized");
  if (!resp.ok) throw new Error(`${path} failed: ${resp.status}`);
  return (await resp.json()) as T;
}

export interface ExtContext {
  facts: Record<string, string>;
  has_resume_file: boolean;
  resume_filename: string | null;
}

export const fetchContext = () => apiFetch<ExtContext>("/api/extension/context");

/** Absolute URL of the resume PDF endpoint. The content script can't attach the
 *  auth header itself, so it routes the download through the background
 *  (FETCH_FILE), which knows the JWT. */
export const resumeFileUrl = () => `${API_BASE}/api/extension/resume-file`;
