import { createClient } from "@/lib/supabase/client";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;

  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  // Caddy exposes frontend and FastAPI on one origin, so the browser image does
  // not need an installation-specific NEXT_PUBLIC_API_URL baked at build time.
  const res = await fetch(path, { ...init, headers });
  const text = await res.text();
  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  let data: unknown = null;

  if (text && isJson) {
    try {
      data = JSON.parse(text);
    } catch {
      if (res.ok) {
        throw new ApiError("Server returned invalid JSON", res.status);
      }
    }
  }

  if (!res.ok) {
    const detail =
      data &&
      typeof data === "object" &&
      ("detail" in data || "message" in data)
        ? (data as { detail?: unknown; message?: unknown }).detail ??
          (data as { message?: unknown }).message
        : null;
    const fallback = text.trim().slice(0, 300);
    const msg = detail || fallback || `HTTP ${res.status}`;
    throw new ApiError(
      typeof msg === "string" ? msg : JSON.stringify(msg),
      res.status,
    );
  }

  if (!isJson) {
    throw new ApiError("Server returned a non-JSON response", res.status);
  }
  return data as T;
}
