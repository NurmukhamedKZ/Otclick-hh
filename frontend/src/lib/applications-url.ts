export type ApplicationsView = {
  status: string;
  q: string;
  /** 0-based internally; exposed in the URL as 1-based `p` */
  page: number;
};

export const APPLICATION_STATUS_IDS = [
  "all",
  "sent",
  "form_sent",
  "captcha",
  "failed",
  "skipped",
  "queued",
] as const;

export const DEFAULT_VIEW: ApplicationsView = { status: "all", q: "", page: 0 };

export function parseView(params: URLSearchParams): ApplicationsView {
  const rawStatus = params.get("status") ?? "";
  const status = (APPLICATION_STATUS_IDS as readonly string[]).includes(rawStatus)
    ? rawStatus
    : DEFAULT_VIEW.status;

  const rawPage = Number.parseInt(params.get("p") ?? "", 10);
  const page = Number.isFinite(rawPage) && rawPage > 0 ? rawPage - 1 : DEFAULT_VIEW.page;

  return { status, q: (params.get("q") ?? "").trim(), page };
}

export function serializeView(view: ApplicationsView): string {
  const params = new URLSearchParams();
  if (view.status !== DEFAULT_VIEW.status) params.set("status", view.status);
  if (view.q.trim()) params.set("q", view.q.trim());
  if (view.page > 0) params.set("p", String(view.page + 1));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}
