"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { NotificationRow } from "@/lib/types";
import { Card, EmptyState, Skeleton } from "@/components/otclick/ui";
import { IBell, IBolt, ICheck, ILink, IShield } from "@/components/otclick/icons";

const ICON: Record<string, React.ReactNode> = {
  captcha: <IShield size={14} />,
  limit_reached: <IBolt size={14} />,
  token_dead: <IShield size={14} />,
  account_banned: <IShield size={14} />,
  worker_stop: <ILink size={14} />,
  resume_missing: <ILink size={14} />,
  recruiter_todo: <ICheck size={14} />,
  recruiter_draft: <ICheck size={14} />,
  form_approval: <ICheck size={14} />,
  cover_letter_written: <ICheck size={14} />,
  web_session_expired: <IShield size={14} />,
};

const BG: Record<string, string> = {
  captcha: "var(--coral)",
  limit_reached: "var(--yellow)",
  token_dead: "var(--err)",
  account_banned: "var(--err)",
  worker_stop: "var(--muted-2)",
  resume_missing: "var(--muted-2)",
  recruiter_todo: "var(--ok)",
  recruiter_draft: "var(--ok)",
  form_approval: "var(--yellow)",
  cover_letter_written: "var(--ok)",
  web_session_expired: "var(--err)",
};

const TITLE: Record<string, string> = {
  captcha: "Нужна капча",
  limit_reached: "Достигнут дневной лимит",
  worker_stop: "Worker остановлен",
  token_dead: "Токен hh умер",
  account_banned: "Аккаунт hh заблокирован",
  resume_missing: "Резюме недоступно",
  recruiter_todo: "Новая задача от рекрутёра",
  recruiter_draft: "Черновик ответа рекрутёру",
  form_approval: "Анкета ждёт подтверждения",
  cover_letter_written: "ИИ написал сопроводительное",
  web_session_expired: "Сессия hh истекла - переподключите аккаунт",
};

function timeAgo(iso: string): string {
  const diff = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff} с`;
  if (diff < 3600) return `${Math.round(diff / 60)} мин`;
  if (diff < 86400) return `${Math.round(diff / 3600)} ч`;
  return `${Math.round(diff / 86400)} дн`;
}

export default function NotificationsCard() {
  const supabase = useMemo(() => createClient(), []);
  const [rows, setRows] = useState<NotificationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data, error } = await supabase
      .from("notifications")
      .select("id,type,payload,read,created_at")
      .order("created_at", { ascending: false })
      .limit(5);
    if (error) {
      setError(error.message);
      return;
    }
    setRows((data ?? []) as NotificationRow[]);
    setError(null);
  }, [supabase]);

  useEffect(() => {
    load();
    const channel = supabase
      .channel("notifications-dashboard")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "notifications" },
        (payload) => {
          setRows((prev) => [payload.new as NotificationRow, ...(prev ?? [])].slice(0, 5));
        },
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [load, supabase]);

  async function markAllRead() {
    await supabase.from("notifications").update({ read: true }).eq("read", false);
    load();
  }

  return (
    <Card>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 14,
        }}
      >
        <div style={{ fontSize: 17, fontWeight: 700 }}>Уведомления</div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            type="button"
            onClick={markAllRead}
            style={{
              background: "transparent",
              border: "none",
              color: "var(--muted)",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            прочитать все
          </button>
          <Link
            href="/notifications"
            style={{ fontSize: 12, fontWeight: 600, color: "var(--ink)", textDecoration: "none" }}
          >
            все →
          </Link>
        </div>
      </div>
      {error && (
        <p style={{ fontSize: 12, color: "var(--err)", marginBottom: 8 }}>{error}</p>
      )}
      {rows === null ? (
        <Skeleton h={40} count={4} />
      ) : rows.length === 0 ? (
        <EmptyState icon={<IBell size={22} />} title="Тихо" description="Здесь появятся события воркера и ИИ-агента." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {rows.map((n, i) => {
            const bg = BG[n.type] ?? "var(--muted-2)";
            const isLight =
              n.type === "limit_reached" ||
              n.type === "worker_stop" ||
              n.type === "form_approval";
            return (
              <Link
                key={n.id}
                href="/notifications"
                style={{ textDecoration: "none", color: "inherit" }}
              >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 4px",
                  borderBottom: i < rows.length - 1 ? "1px solid var(--line-2)" : "none",
                }}
              >
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 10,
                    background: bg,
                    color: isLight ? "var(--ink)" : "#fff",
                    display: "grid",
                    placeItems: "center",
                    flexShrink: 0,
                  }}
                >
                  {ICON[n.type] ?? <ILink size={14} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: n.read ? 500 : 600,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {TITLE[n.type] ?? n.type}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 1 }}>
                    {timeAgo(n.created_at)} назад
                  </div>
                </div>
                  {!n.read && (
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 999,
                      background: "var(--coral)",
                      flexShrink: 0,
                    }}
                  />
                )}
              </div>
              </Link>
            );
          })}
        </div>
      )}
    </Card>
  );
}
