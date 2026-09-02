"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Application } from "@/lib/types";
import { Card, EmptyState, LinkBtn, Skeleton, Tag } from "@/components/otclick/ui";
import { IList, IPlus } from "@/components/otclick/icons";
import { openFiltersDrawer } from "@/components/filters-drawer";

const LIMIT = 8;

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

export default function RecentApplicationsCard() {
  const [rows, setRows] = useState<Application[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const supabase = useMemo(() => createClient(), []);

  const load = useCallback(async () => {
    const { data, error } = await supabase
      .from("applications")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(LIMIT);
    if (error) {
      setError(error.message);
      return;
    }
    setRows((data ?? []) as Application[]);
    setError(null);
  }, [supabase]);

  useEffect(() => {
    let cancelled = false;
    let channel: ReturnType<typeof supabase.channel> | null = null;
    (async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user || cancelled) return;
      await load();
      const filter = `user_id=eq.${user.id}`;
      channel = supabase
        .channel("dashboard-applications")
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "applications", filter },
          (payload) => {
            const row = payload.new as Application;
            setRows((prev) =>
              [row, ...(prev ?? []).filter((r) => r.id !== row.id)].slice(0, LIMIT),
            );
          },
        )
        .on(
          "postgres_changes",
          { event: "UPDATE", schema: "public", table: "applications", filter },
          (payload) => {
            const row = payload.new as Application;
            setRows((prev) => (prev ?? []).map((r) => (r.id === row.id ? row : r)));
          },
        )
        .subscribe();
    })();
    return () => {
      cancelled = true;
      if (channel) supabase.removeChannel(channel);
    };
  }, [load, supabase]);

  return (
    <Card>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 17, fontWeight: 700 }}>Последние отклики</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            обновляется в реальном времени
          </div>
        </div>
        <LinkBtn href="/applications" kind="primary" size="sm" icon={<IPlus size={13} />}>
          все отклики
        </LinkBtn>
      </div>
      {error && (
        <p style={{ fontSize: 12, color: "var(--err)", marginBottom: 8 }}>{error}</p>
      )}
      {rows === null ? (
        <Skeleton h={60} count={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<IList size={22} />}
          title="Откликов пока нет"
          description="Настрой фильтры и запусти автоотклик — первые отклики появятся здесь."
          action={{ label: "Настроить фильтры", onClick: openFiltersDrawer }}
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {rows.map((a) => {
            const s = STATUS_TAG[a.status] ?? { tone: "neutral" as const, label: a.status };
            const initial = (a.employer_id ?? a.vacancy_id ?? "?")[0]?.toUpperCase() ?? "?";
            return (
              <div
                key={a.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  padding: "12px 14px",
                  borderRadius: 14,
                  background: "var(--bg-deep)",
                }}
              >
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 12,
                    background: "#fff",
                    color: "var(--ink)",
                    display: "grid",
                    placeItems: "center",
                    fontSize: 12,
                    fontWeight: 700,
                    border: "1px solid var(--line)",
                    flexShrink: 0,
                  }}
                >
                  {initial}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <a
                    href={`https://hh.ru/vacancy/${a.vacancy_id}`}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: "var(--ink)",
                      textDecoration: "none",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      display: "block",
                    }}
                  >
                    {a.vacancy_title?.trim() || `Вакансия ${a.vacancy_id}`}
                  </a>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                    {a.employer_name?.trim() || a.employer_id || "—"}
                    {a.error ? ` · ${a.error}` : ""}
                  </div>
                </div>
                {(a.cover_letter ?? "").trim() && (
                  <Tag tone="neutral">✎ AI</Tag>
                )}
                <Tag tone={s.tone} dot>
                  {s.label}
                </Tag>
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--muted)",
                    minWidth: 42,
                    textAlign: "right",
                  }}
                >
                  {timeAgo(a.created_at)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
