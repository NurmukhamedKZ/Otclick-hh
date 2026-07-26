"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Resume, ResumesList } from "@/lib/types";
import { Btn, Card, EmptyState, Skeleton, Tag } from "@/components/otclick/ui";
import { IDoc, IRefresh } from "@/components/otclick/icons";
import { pushToast } from "@/components/toaster";

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const diff = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff} с назад`;
  if (diff < 3600) return `${Math.round(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.round(diff / 3600)} ч назад`;
  return `${Math.round(diff / 86400)} дн назад`;
}

export default function ResumesCard() {
  const [items, setItems] = useState<Resume[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<ResumesList>("/api/resumes");
      setItems(data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function sync() {
    setSyncing(true);
    setError(null);
    try {
      const data = await apiFetch<ResumesList>("/api/resumes/sync", { method: "POST" });
      setItems(data.items);
      pushToast({ kind: "success", title: "резюме синхронизированы" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "sync failed");
    } finally {
      setSyncing(false);
    }
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
        <div style={{ fontSize: 17, fontWeight: 700 }}>Мои резюме</div>
        <Btn kind="soft" size="sm" icon={<IRefresh size={14} />} onClick={sync} disabled={syncing}>
          {syncing ? "синк…" : "синхронизировать"}
        </Btn>
      </div>
      {error && (
        <p style={{ fontSize: 12, color: "var(--err)", marginBottom: 8 }}>{error}</p>
      )}
      {items === null ? (
        <Skeleton h={62} count={2} />
      ) : items.length === 0 ? (
        <EmptyState icon={<IDoc size={22} />} title="Резюме не найдены" description="Синхронизируй резюме с hh, чтобы автоотклик знал, чем откликаться." action={{ label: "Синхронизировать", onClick: sync }} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((r) => {
            const active = r.status === "published";
            return (
              <div
                key={r.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  padding: "12px 14px",
                  background: "var(--bg-deep)",
                  borderRadius: 14,
                }}
              >
                <div
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: 12,
                    flexShrink: 0,
                    background: active ? "var(--ink)" : "transparent",
                    color: active ? "#F5F1E6" : "var(--muted)",
                    border: active ? "none" : "1px dashed var(--muted-2)",
                    display: "grid",
                    placeItems: "center",
                  }}
                >
                  <IDoc size={16} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {r.title ?? r.hh_resume_id}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                    синхронизировано {timeAgo(r.synced_at)}
                  </div>
                </div>
                {active ? (
                  <Tag tone="dark" dot>
                    активно
                  </Tag>
                ) : (
                  <Tag tone="neutral">{r.status ?? "—"}</Tag>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
