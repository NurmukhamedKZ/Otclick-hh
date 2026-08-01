import { getValidJwt } from "./auth";
import type { ChatMsg } from "./chat-store";

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

// ── Autofill ────────────────────────────────────────────────────────────────

export interface FilledField {
  frame_id: number;
  ref: string;
  selector: string;
  field_type: string;
  value: string;
  source: "profile" | "ai";
  filename?: string;
  required?: boolean;
}

export interface FillResponse {
  frames: { frame_id: number; fields: FilledField[] }[];
}

const MAX_PAGE_TEXT = 40_000; // mirrors the backend's FillRequest limit

export function buildFillPayload(input: {
  url: string;
  pageText: string;
  frames: { frame_id: number; snapshot: unknown[] }[];
}) {
  return {
    url: input.url,
    page_text: input.pageText.slice(0, MAX_PAGE_TEXT),
    frames: input.frames,
  };
}

export function mergeFrameFields(resp: FillResponse, frameId: number): FilledField[] {
  return resp.frames.find((f) => f.frame_id === frameId)?.fields ?? [];
}

/** The backend echoes refs, not labels; renderMarks and the edit diff both need
 *  a human label, so join them back from the snapshot we just took. */
export function withLabels(
  fields: FilledField[],
  els: { ref: string; label?: string }[],
): (FilledField & { label: string })[] {
  const labels = new Map(els.map((e) => [e.ref, e.label ?? ""]));
  return fields.map((f) => ({ ...f, label: labels.get(f.ref) ?? "" }));
}

export const callFill = (payload: ReturnType<typeof buildFillPayload>) =>
  apiFetch<FillResponse>("/api/extension/fill", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ── Chat ────────────────────────────────────────────────────────────────────

export const callChat = (messages: ChatMsg[], pageText?: string) =>
  apiFetch<{ answer: string }>("/api/extension/chat", {
    method: "POST",
    body: JSON.stringify({ messages, page_text: pageText ?? null }),
  }).then((r) => r.answer);
