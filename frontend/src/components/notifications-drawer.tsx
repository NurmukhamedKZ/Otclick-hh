"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import type { NotificationRow } from "@/lib/types";
import { Btn } from "@/components/otclick/ui";
import { IBolt, ICheck, IClose, ILink, IShield, ITrash } from "@/components/otclick/icons";

const EVENT = "notifications-drawer";

export function openNotificationsDrawer() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { open: true } }));
}

const ICON: Record<string, React.ReactNode> = {
  captcha: <IShield size={14} />,
  limit_reached: <IBolt size={14} />,
  token_dead: <IClose size={14} />,
  account_banned: <IClose size={14} />,
  worker_stop: <ILink size={14} />,
  resume_missing: <ILink size={14} />,
  recruiter_todo: <ICheck size={14} />,
  recruiter_draft: <ICheck size={14} />,
  recruiter_question: <ICheck size={14} />,
  form_approval: <ICheck size={14} />,
  cover_letter_written: <ICheck size={14} />,
  web_session_expired: <IClose size={14} />,
};

const COLOR: Record<string, string> = {
  captcha: "var(--coral)",
  limit_reached: "var(--yellow)",
  token_dead: "var(--err)",
  account_banned: "var(--err)",
  worker_stop: "var(--muted-2)",
  resume_missing: "var(--muted-2)",
  recruiter_todo: "var(--ok)",
  recruiter_draft: "var(--ok)",
  recruiter_question: "var(--ok)",
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
  recruiter_question: "Вопрос от ИИ-агента",
  form_approval: "Анкета ждёт подтверждения",
  cover_letter_written: "ИИ написал сопроводительное",
  web_session_expired: "Сессия hh истекла - переподключите аккаунт",
};

function bucketLabel(d: Date): string {
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (sameDay(d, today)) return "сегодня";
  if (sameDay(d, yesterday)) return "вчера";
  return "ранее";
}

function timeStr(iso: string): string {
  const d = new Date(iso);
  const diffMin = Math.round((Date.now() - d.getTime()) / 60000);
  if (diffMin < 1) return "только что";
  if (diffMin < 60) return `${diffMin} мин`;
  if (diffMin < 1440) return `${Math.round(diffMin / 60)} ч`;
  return d.toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export default function NotificationsDrawer() {
  const [open, setOpen] = useState(false);
  const supabase = useMemo(() => createClient(), []);
  const [rows, setRows] = useState<NotificationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    function onToggle(e: Event) {
      const detail = (e as CustomEvent<{ open: boolean }>).detail;
      setOpen(!!detail?.open);
    }
    window.addEventListener(EVENT, onToggle);
    return () => window.removeEventListener(EVENT, onToggle);
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    if (open) {
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
  }, [open]);

  const load = useCallback(async () => {
    const { data, error } = await supabase
      .from("notifications")
      .select("id,type,payload,read,created_at")
      .order("created_at", { ascending: false })
      .limit(50);
    if (error) {
      setError(error.message);
      return;
    }
    setRows((data ?? []) as NotificationRow[]);
  }, [supabase]);

  useEffect(() => {
    load();
    const channel = supabase
      .channel("notifications-drawer")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "notifications" },
        (payload) => {
          setRows((prev) => [payload.new as NotificationRow, ...(prev ?? [])].slice(0, 50));
        },
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [load, supabase]);

  async function markAllRead() {
    setBusy(true);
    await supabase.from("notifications").update({ read: true }).eq("read", false);
    setBusy(false);
    load();
  }

  async function clearAll() {
    if (!confirm("Удалить все уведомления?")) return;
    setBusy(true);
    await supabase
      .from("notifications")
      .delete()
      .neq("id", "00000000-0000-0000-0000-000000000000");
    setBusy(false);
    setRows([]);
  }

  const groups = new Map<string, NotificationRow[]>();
  for (const n of rows ?? []) {
    const k = bucketLabel(new Date(n.created_at));
    const arr = groups.get(k) ?? [];
    arr.push(n);
    groups.set(k, arr);
  }

  return (
    <>
      <div
        onClick={() => setOpen(false)}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.3)",
          opacity: open ? 1 : 0,
          pointerEvents: open ? "auto" : "none",
          transition: "opacity .25s",
          zIndex: 50,
        }}
      />
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: "min(640px, 96vw)",
          background: "var(--bg)",
          transform: open ? "translateX(0)" : "translateX(100%)",
          transition: "transform .3s cubic-bezier(.2,.8,.2,1)",
          zIndex: 51,
          padding: 24,
          overflow: "auto",
          boxShadow: "-20px 0 60px rgba(0,0,0,0.15)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 18,
            flexWrap: "wrap",
            gap: 10,
          }}
        >
          <div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>Уведомления</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
              события воркера и ИИ-агента
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Btn kind="ghost" size="sm" icon={<ICheck size={13} />} onClick={markAllRead} disabled={busy}>
              прочитать все
            </Btn>
            <Btn kind="ghost" size="sm" icon={<ITrash size={13} />} onClick={clearAll} disabled={busy}>
              очистить
            </Btn>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="close"
              style={{
                width: 36,
                height: 36,
                borderRadius: 12,
                border: "none",
                background: "var(--surface)",
                display: "grid",
                placeItems: "center",
                cursor: "pointer",
                color: "var(--ink)",
                flexShrink: 0,
              }}
            >
              <IClose size={18} />
            </button>
          </div>
        </div>

        {error && (
          <p style={{ color: "var(--err)", fontSize: 13, marginBottom: 10 }}>{error}</p>
        )}
        {rows === null ? (
          <p style={{ color: "var(--muted)", fontSize: 13 }}>загрузка…</p>
        ) : rows.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: 13 }}>пусто</p>
        ) : (
          [...groups.entries()].map(([label, items]) => (
            <div key={label} style={{ marginBottom: 18 }}>
              <div
                style={{
                  fontSize: 11,
                  color: "var(--muted)",
                  textTransform: "uppercase",
                  letterSpacing: 0.8,
                  fontWeight: 700,
                  marginBottom: 10,
                }}
              >
                {label}
              </div>
              {items.map((n, i) => {
                const bg = COLOR[n.type] ?? "var(--muted-2)";
                const isLight = n.type === "limit_reached" || n.type === "worker_stop";
                return (
                  <div
                    key={n.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      padding: "12px 14px",
                      borderRadius: 14,
                      background: i % 2 === 0 ? "var(--bg-deep)" : "transparent",
                      marginBottom: 4,
                    }}
                  >
                    <div
                      style={{
                        width: 34,
                        height: 34,
                        borderRadius: 11,
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
                      <div style={{ fontSize: 14, fontWeight: 600 }}>
                        {TITLE[n.type] ?? n.type}
                      </div>
                      {n.payload && (
                        <div
                          style={{
                            fontSize: 11,
                            color: "var(--muted)",
                            marginTop: 2,
                            fontFamily: "JetBrains Mono, monospace",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {JSON.stringify(n.payload)}
                        </div>
                      )}
                    </div>
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>
                      {timeStr(n.created_at)}
                    </span>
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>
    </>
  );
}
