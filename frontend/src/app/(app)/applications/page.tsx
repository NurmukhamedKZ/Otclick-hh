"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Application } from "@/lib/types";
import { Btn, Card, PageHeader, Tag } from "@/components/otclick/ui";
import { IExternal, IRefresh, ISearch } from "@/components/otclick/icons";

const PAGE_SIZE = 25;

const STATUSES = [
  { id: "all", label: "все", tone: "dark" as const },
  { id: "sent", label: "отправленные", tone: "ok" as const },
  { id: "form_sent", label: "с тестом", tone: "ok" as const },
  { id: "captcha", label: "капча", tone: "coral" as const },
  { id: "failed", label: "ошибки", tone: "err" as const },
  { id: "skipped", label: "пропущенные", tone: "neutral" as const },
  { id: "queued", label: "в очереди", tone: "neutral" as const },
];

const STATUS_TAG: Record<string, { tone: "ok" | "coral" | "err" | "neutral"; label: string }> = {
  sent: { tone: "ok", label: "отправлено" },
  form_sent: { tone: "ok", label: "форма ✓" },
  captcha: { tone: "coral", label: "капча" },
  failed: { tone: "err", label: "ошибка" },
  skipped: { tone: "neutral", label: "пропуск" },
  queued: { tone: "neutral", label: "очередь" },
  form_required: { tone: "coral", label: "форма" },
  vacancy_gone: { tone: "neutral", label: "удалена" },
};

function timeAgo(iso: string): string {
  const diff = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff} с`;
  if (diff < 3600) return `${Math.round(diff / 60)} мин`;
  if (diff < 86400) return `${Math.round(diff / 3600)} ч`;
  return `${Math.round(diff / 86400)} дн`;
}

export default function ApplicationsPage() {
  const supabase = useMemo(() => createClient(), []);
  const [rows, setRows] = useState<Application[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [status, setStatus] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setSearchDebounced(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    setRows(null);
    let q = supabase
      .from("applications")
      .select("*", { count: "exact" })
      .order("created_at", { ascending: false })
      .range(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE - 1);

    if (status !== "all") q = q.eq("status", status);
    if (searchDebounced) {
      q = q.or(
        `vacancy_id.ilike.%${searchDebounced}%,employer_id.ilike.%${searchDebounced}%`,
      );
    }

    const { data, count, error } = await q;
    if (error) {
      setError(error.message);
      return;
    }
    setRows((data ?? []) as Application[]);
    setTotal(count ?? 0);
    setError(null);
  }, [supabase, page, status, searchDebounced]);

  const loadCounts = useCallback(async () => {
    const next: Record<string, number> = {};
    const { count: all } = await supabase
      .from("applications")
      .select("*", { count: "exact", head: true });
    next.all = all ?? 0;
    for (const s of STATUSES.filter((s) => s.id !== "all")) {
      const { count } = await supabase
        .from("applications")
        .select("*", { count: "exact", head: true })
        .eq("status", s.id);
      next[s.id] = count ?? 0;
    }
    setCounts(next);
  }, [supabase]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadCounts();
  }, [loadCounts]);

  useEffect(() => {
    let cancelled = false;
    let channel: ReturnType<typeof supabase.channel> | null = null;
    (async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user || cancelled) return;
      const filter = `user_id=eq.${user.id}`;
      channel = supabase
        .channel("applications-page")
        .on(
          "postgres_changes",
          { event: "*", schema: "public", table: "applications", filter },
          () => {
            if (page === 0) load();
            loadCounts();
          },
        )
        .subscribe();
    })();
    return () => {
      cancelled = true;
      if (channel) supabase.removeChannel(channel);
    };
  }, [supabase, load, loadCounts, page]);

  function refresh() {
    setSpinning(true);
    load();
    loadCounts();
    setTimeout(() => setSpinning(false), 600);
  }

  const pages = Math.ceil(total / PAGE_SIZE);

  return (
    <>
      <PageHeader title="Отклики" subtitle="все попытки отклика и их результат" crumbs={[{ label: "Главная", href: "/dashboard" }, { label: "Отклики" }]} />
      <Card style={{ marginBottom: 18 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            marginBottom: 16,
            flexWrap: "wrap",
          }}
        >
          <div style={{ fontSize: 19, fontWeight: 700 }}>Все отклики</div>
          <Tag tone="dark" dot>
            realtime
          </Tag>
          <div style={{ flex: 1 }} />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: "var(--bg-deep)",
              borderRadius: 999,
              padding: "8px 14px",
              minWidth: 240,
            }}
          >
            <ISearch size={16} stroke="var(--muted)" />
            <input
              placeholder="vacancy_id, employer_id…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
              style={{
                flex: 1,
                border: "none",
                outline: "none",
                background: "transparent",
                fontSize: 13,
                fontFamily: "inherit",
                color: "var(--ink)",
                minWidth: 0,
              }}
            />
          </div>
          <Btn
            kind="ghost"
            size="sm"
            icon={
              <IRefresh
                size={14}
                style={spinning ? { animation: "oc-spin 0.6s linear infinite" } : undefined}
              />
            }
            onClick={refresh}
          >
            обновить
          </Btn>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {STATUSES.map((f) => (
            <button
              type="button"
              key={f.id}
              onClick={() => {
                setStatus(f.id);
                setPage(0);
              }}
              style={{
                border: "none",
                background: status === f.id ? "var(--ink)" : "var(--bg-deep)",
                color: status === f.id ? "#F5F1E6" : "var(--ink)",
                padding: "8px 14px",
                borderRadius: 999,
                fontSize: 13,
                fontWeight: 600,
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              {f.label}
              <span
                className="mono"
                style={{
                  background: status === f.id ? "#ffffff15" : "#ffffff",
                  padding: "2px 7px",
                  borderRadius: 999,
                  fontSize: 11,
                }}
              >
                {counts[f.id] ?? 0}
              </span>
            </button>
          ))}
        </div>
      </Card>

      <Card className="oc-scroll-x" style={{ padding: 0, overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "120px minmax(160px, 1fr) 160px minmax(140px, 1fr) 100px 60px",
            gap: 14,
            padding: "14px 22px",
            fontSize: 11,
            color: "var(--muted)",
            textTransform: "uppercase",
            letterSpacing: 0.5,
            fontWeight: 600,
            borderBottom: "1px solid var(--line-2)",
          }}
        >
          <div>статус</div>
          <div>вакансия</div>
          <div>работодатель</div>
          <div>комментарий</div>
          <div>время</div>
          <div></div>
        </div>
        {error && (
          <p style={{ fontSize: 13, color: "var(--err)", padding: "12px 22px" }}>{error}</p>
        )}
        {rows === null ? (
          <p style={{ fontSize: 13, color: "var(--muted)", padding: "22px" }}>загрузка…</p>
        ) : rows.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--muted)", padding: "22px" }}>
            откликов нет
          </p>
        ) : (
          rows.map((a, i) => {
            const s = STATUS_TAG[a.status] ?? { tone: "neutral" as const, label: a.status };
            const qa = a.form_answers ?? [];
            const letter = (a.cover_letter ?? "").trim();
            const open = openId === a.id;
            return (
              <Fragment key={a.id}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "120px minmax(160px, 1fr) 160px minmax(140px, 1fr) 100px 60px",
                  gap: 14,
                  padding: "16px 22px",
                  alignItems: "center",
                  fontSize: 13,
                  borderBottom: i < rows.length - 1 ? "1px solid var(--line-2)" : "none",
                  transition: "background .15s",
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLDivElement).style.background = "var(--bg-deep)")
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLDivElement).style.background = "transparent")
                }
              >
                <Tag tone={s.tone} dot>
                  {s.label}
                </Tag>
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 600,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    vacancy {a.vacancy_id}
                  </div>
                  {a.resume_id && (
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                      резюме {a.resume_id.slice(0, 8)}
                    </div>
                  )}
                  {qa.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setOpenId(open ? null : a.id)}
                      style={{
                        marginTop: 4,
                        border: "none",
                        background: "transparent",
                        padding: 0,
                        cursor: "pointer",
                        fontFamily: "inherit",
                        fontSize: 11,
                        fontWeight: 600,
                        color: "var(--coral)",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                      }}
                    >
                      {open ? "▾" : "▸"} тест · {qa.length} вопр.
                    </button>
                  )}
                  {qa.length === 0 && letter && (
                    <button
                      type="button"
                      onClick={() => setOpenId(open ? null : a.id)}
                      style={{
                        marginTop: 4,
                        border: "none",
                        background: "transparent",
                        padding: 0,
                        cursor: "pointer",
                        fontFamily: "inherit",
                        fontSize: 11,
                        fontWeight: 600,
                        color: "var(--coral)",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                      }}
                    >
                      {open ? "▾" : "▸"} AI письмо
                    </button>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <div
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: 8,
                      background: "var(--bg-deep)",
                      display: "grid",
                      placeItems: "center",
                      fontSize: 11,
                      fontWeight: 700,
                      flexShrink: 0,
                    }}
                  >
                    {a.employer_id?.[0]?.toUpperCase() ?? "?"}
                  </div>
                  <span
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {a.employer_id ?? "—"}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: a.error ? "var(--coral)" : "var(--muted)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {a.error || "—"}
                </div>
                <div className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
                  {timeAgo(a.created_at)} назад
                </div>
                <a
                  href={`https://hh.ru/vacancy/${a.vacancy_id}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "var(--ink)", display: "inline-flex" }}
                >
                  <IExternal size={15} />
                </a>
              </div>
              {open && qa.length > 0 && (
                <div
                  style={{
                    padding: "2px 22px 18px",
                    background: "var(--bg-deep)",
                    borderBottom: i < rows.length - 1 ? "1px solid var(--line-2)" : "none",
                  }}
                >
                  {qa.map((q, qi) => (
                    <div key={q.task_id ?? qi} style={{ marginTop: qi ? 14 : 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)" }}>
                        {qi + 1}. {q.question || "(без текста)"}
                      </div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
                        {q.type === "choice" ? "выбор" : "ответ"}:{" "}
                        <span style={{ color: "var(--ink)", fontWeight: 600 }}>
                          {q.answer || "—"}
                        </span>
                      </div>
                      {q.type === "choice" && q.options && q.options.length > 0 && (
                        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                          варианты: {q.options.map((o) => o.text).join(" · ")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {open && qa.length === 0 && letter && (
                <div
                  style={{
                    padding: "2px 22px 18px",
                    background: "var(--bg-deep)",
                    borderBottom: i < rows.length - 1 ? "1px solid var(--line-2)" : "none",
                  }}
                >
                  <div
                    style={{
                      fontSize: 12,
                      color: "var(--ink)",
                      whiteSpace: "pre-wrap",
                      lineHeight: 1.5,
                    }}
                  >
                    {letter}
                  </div>
                </div>
              )}
              </Fragment>
            );
          })
        )}
        {pages > 1 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "14px 22px",
              fontSize: 12,
              color: "var(--muted)",
              borderTop: "1px solid var(--line-2)",
            }}
          >
            <span>
              стр. {page + 1} из {pages}
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                style={pagerBtn(false)}
              >
                ‹
              </button>
              <button type="button" style={pagerBtn(true)}>{page + 1}</button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
                disabled={page + 1 >= pages}
                style={pagerBtn(false)}
              >
                ›
              </button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}

function pagerBtn(active: boolean): React.CSSProperties {
  return {
    padding: "6px 12px",
    border: active ? "none" : "1px solid var(--line)",
    background: active ? "var(--ink)" : "transparent",
    color: active ? "#F5F1E6" : "var(--ink)",
    borderRadius: 8,
    fontWeight: 600,
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: 13,
  };
}
