"use client";

import { Fragment, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import type { Application } from "@/lib/types";
import { Btn, Card, EmptyState, Pager, SegmentedTabs, Skeleton, Tag } from "@/components/otclick/ui";
import { IExternal, IList, IRefresh, ISearch } from "@/components/otclick/icons";
import {
  DEFAULT_VIEW,
  parseView,
  sanitizeSearch,
  serializeView,
  type ApplicationsView,
} from "@/lib/applications-url";
import { openFiltersDrawer } from "@/components/filters-drawer";

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
  return (
    <Suspense fallback={<div style={{ padding: 22 }}><Skeleton h={44} count={6} /></div>}>
      <ApplicationsView />
    </Suspense>
  );
}

function ApplicationsView() {
  const supabase = useMemo(() => createClient(), []);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const view = useMemo(() => parseView(new URLSearchParams(searchParams.toString())), [searchParams]);
  const { status, page } = view;

  const [rows, setRows] = useState<Application[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState(view.q);
  const [spinning, setSpinning] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const setView = useCallback(
    // "push" for discrete choices (a tab, a page) so the back button steps through
    // them; "replace" for debounced typing, which would otherwise flood the history
    // with one entry per keystroke.
    (patch: Partial<ApplicationsView>, history: "push" | "replace" = "push") => {
      const next = { ...view, ...patch };
      const url = `${pathname}${serializeView(next)}`;
      if (history === "push") router.push(url, { scroll: false });
      else router.replace(url, { scroll: false });
    },
    [view, pathname, router],
  );

  // Last query this component pushed into the URL. Without it the debounce below
  // cannot tell "the user typed" from "the URL changed underneath us", and would
  // push the stale input back — breaking the back button and the reset action.
  const pushedQ = useRef(view.q);

  // URL changed externally (back/forward, reset button, shared link) → input follows
  useEffect(() => {
    if (view.q !== pushedQ.current) {
      pushedQ.current = view.q;
      setSearch(view.q);
    }
  }, [view.q]);

  // local typing → URL, debounced
  useEffect(() => {
    if (search.trim() === pushedQ.current) return;
    const t = setTimeout(() => {
      pushedQ.current = search.trim();
      setView({ q: search.trim(), page: 0 }, "replace");
    }, 300);
    return () => clearTimeout(t);
  }, [search, setView]);

  const load = useCallback(async () => {
    setRows(null);
    let q = supabase
      .from("applications")
      .select("*", { count: "exact" })
      .order("created_at", { ascending: false })
      .range(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE - 1);

    if (status !== "all") q = q.eq("status", status);
    const term = sanitizeSearch(view.q);
    if (term) {
      q = q.or(`vacancy_id.ilike.%${term}%,employer_id.ilike.%${term}%,vacancy_title.ilike.%${term}%,employer_name.ilike.%${term}%`);
    }

    const { data, count, error } = await q;
    if (error) {
      setError(error.message);
      return;
    }
    setRows((data ?? []) as Application[]);
    setTotal(count ?? 0);
    setError(null);
  }, [supabase, page, status, view.q]);

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
              placeholder="vacancy, работодатель…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
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
        <SegmentedTabs
          items={STATUSES.map((s) => ({ id: s.id, label: s.label, count: counts[s.id] ?? 0 }))}
          value={status}
          onChange={(id) => setView({ status: id, page: 0 })}
          label="Статус отклика"
        />
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
          <div style={{ padding: 22 }}><Skeleton h={44} count={6} /></div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<IList size={22} />}
            title={status === "all" && !view.q ? "Откликов пока нет" : "Ничего не найдено"}
            description={
              status === "all" && !view.q
                ? "Запусти автоотклик — результаты появятся здесь в реальном времени."
                : "Попробуй сбросить фильтр или изменить запрос."
            }
            action={
              status === "all" && !view.q
                ? { label: "Настроить фильтры", onClick: openFiltersDrawer }
                : { label: "Сбросить фильтры", onClick: () => setView(DEFAULT_VIEW) }
            }
          />
        ) : (
          rows.map((a, i) => {
            const s = STATUS_TAG[a.status] ?? { tone: "neutral" as const, label: a.status };
            const qa = a.form_answers ?? [];
            const letter = (a.cover_letter ?? "").trim();
            const open = openId === a.id;
            const expandable = qa.length > 0 || !!letter;
            const toggle = () => setOpenId(open ? null : a.id);
            return (
              <Fragment key={a.id}>
              <div
                className="oc-row"
                // mouse convenience only — the keyboard path is the button below,
                // because role="button" may not contain the hh.ru link.
                onClick={expandable ? toggle : undefined}
                style={{
                  display: "grid",
                  gridTemplateColumns: "120px minmax(160px, 1fr) 160px minmax(140px, 1fr) 100px 60px",
                  gap: 14,
                  padding: "16px 22px",
                  alignItems: "center",
                  fontSize: 13,
                  borderBottom: i < rows.length - 1 ? "1px solid var(--line-2)" : "none",
                  cursor: expandable ? "pointer" : "default",
                }}
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
                    {a.vacancy_title ? a.vacancy_title : `Вакансия ${a.vacancy_id}`}
                  </div>
                  {a.resume_id && (
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                      резюме {a.resume_id.slice(0, 8)}
                    </div>
                  )}
                  {expandable && (
                    <button
                      type="button"
                      aria-expanded={open}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggle();
                      }}
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
                      }}
                    >
                      {open ? "▾" : "▸"} {qa.length > 0 ? `тест · ${qa.length} вопр.` : "AI письмо"}
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
                    {a.employer_name ? a.employer_name : (a.employer_id ?? "—")}
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
                  aria-label="открыть вакансию на hh.ru"
                  onClick={(e) => e.stopPropagation()}
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
            <Pager page={page} pages={pages} onChange={(p) => setView({ page: p })} />
          </div>
        )}
      </Card>
    </>
  );
}
