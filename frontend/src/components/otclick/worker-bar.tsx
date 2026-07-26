"use client";

import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type {
  AgentStartResponse,
  AgentStopResponse,
  WorkerStartResponse,
  WorkerStatus,
  WorkerStopResponse,
} from "@/lib/types";
import { StatusDot } from "@/components/otclick/ui";
import { IFilter, IPause, IPlay, IRefresh, ISpark } from "@/components/otclick/icons";
import { pushToast } from "@/components/toaster";
import { openFiltersDrawer } from "@/components/filters-drawer";

const STATE_LABEL: Record<WorkerStatus["state"], string> = {
  running: "работает",
  paused_captcha: "капча",
  paused_limit: "лимит",
  stopped: "остановлен",
};

function nextRunText(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const diff = Math.round((t - Date.now()) / 1000);
  if (diff <= 0) return "сейчас";
  if (diff < 60) return `через ${diff} с`;
  const m = Math.round(diff / 60);
  return `через ${m} мин`;
}

export default function WorkerBar() {
  const qc = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  const { data: status } = useQuery({
    queryKey: ["worker-status"],
    queryFn: () => apiFetch<WorkerStatus>("/api/worker/status"),
    refetchInterval: 5000,
  });

  const startM = useMutation({
    mutationFn: () =>
      apiFetch<WorkerStartResponse>("/api/worker/start", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker-status"] });
      pushToast({ kind: "success", title: "worker запущен" });
    },
    onError: (e) => pushToast({ kind: "error", title: e instanceof Error ? e.message : "start failed" }),
  });

  const stopM = useMutation({
    mutationFn: () =>
      apiFetch<WorkerStopResponse>("/api/worker/stop", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker-status"] });
      pushToast({ kind: "info", title: "worker остановлен" });
    },
    onError: (e) => pushToast({ kind: "error", title: e instanceof Error ? e.message : "stop failed" }),
  });

  const agentStartM = useMutation({
    mutationFn: () =>
      apiFetch<AgentStartResponse>("/api/worker/agent/start", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker-status"] });
      pushToast({ kind: "success", title: "ИИ-агент запущен" });
    },
    onError: (e) => pushToast({ kind: "error", title: e instanceof Error ? e.message : "start failed" }),
  });

  const agentStopM = useMutation({
    mutationFn: () =>
      apiFetch<AgentStopResponse>("/api/worker/agent/stop", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker-status"] });
      pushToast({ kind: "info", title: "ИИ-агент остановлен" });
    },
    onError: (e) => pushToast({ kind: "error", title: e instanceof Error ? e.message : "stop failed" }),
  });

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await qc.invalidateQueries({ queryKey: ["worker-status"] });
    setTimeout(() => setRefreshing(false), 400);
  }, [qc]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "r" && (e.ctrlKey || e.metaKey) && e.shiftKey) {
        e.preventDefault();
        refresh();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [refresh]);

  const state = status?.state ?? "stopped";
  const isRunning = state === "running";
  const isErr = !!status?.last_error;
  const dot = isErr ? "err" : isRunning ? "ok" : state === "paused_captcha" || state === "paused_limit" ? "warn" : "muted";
  const label = STATE_LABEL[state];
  const busy = startM.isPending || stopM.isPending;
  const agentRunning = (status?.agent_state ?? "stopped") === "running";
  const agentBusy = agentStartM.isPending || agentStopM.isPending;

  return (
    <div
      style={{
        background: "var(--ink)",
        color: "#F5F1E6",
        borderRadius: 18,
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        gap: 18,
        marginBottom: 18,
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ position: "relative", display: "inline-flex" }}>
          <StatusDot tone={dot as "ok" | "warn" | "err" | "muted"} size={9} />
          {isRunning && (
            <span
              style={{
                position: "absolute",
                inset: -4,
                borderRadius: 999,
                border: "1px solid var(--ok)",
                opacity: 0.5,
                animation: "oc-pulse 1.6s infinite",
              }}
            />
          )}
        </span>
        <span style={{ fontWeight: 600, fontSize: 14 }}>автоотклик · {label}</span>
      </div>
      <div style={{ height: 18, width: 1, background: "#ffffff15" }} />
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <StatusDot tone={agentRunning ? "ok" : "muted"} size={9} />
        <span style={{ fontWeight: 600, fontSize: 14 }}>
          ИИ-агент · {agentRunning ? "работает" : "остановлен"}
        </span>
      </div>
      <div style={{ height: 18, width: 1, background: "#ffffff15" }} />
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, fontSize: 13 }}>
        <span style={{ color: "#ffffff80" }}>сегодня</span>
        <span className="mono" style={{ fontWeight: 600 }}>
          {status?.today_count ?? 0}
          <span style={{ color: "#ffffff50" }}>/{status?.daily_limit ?? "—"}</span>
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, fontSize: 13 }}>
        <span style={{ color: "#ffffff80" }}>в очереди</span>
        <span className="mono" style={{ fontWeight: 600 }}>{status?.queued ?? 0}</span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, fontSize: 13 }}>
        <span style={{ color: "#ffffff80" }}>след. запуск</span>
        <span className="mono" style={{ fontWeight: 600 }}>{nextRunText(status?.next_run_at ?? null)}</span>
      </div>
      {status?.last_error && (
        <div
          style={{
            background: "#ffffff10",
            color: "var(--coral-soft)",
            padding: "4px 10px",
            borderRadius: 999,
            fontSize: 12,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span>⚠</span> {status.last_error}
        </div>
      )}
      <div style={{ flex: 1 }} />
      <button
        type="button"
        onClick={openFiltersDrawer}
        style={{
          border: "none",
          background: "#ffffff15",
          color: "#F5F1E6",
          borderRadius: 999,
          padding: "8px 14px",
          fontWeight: 600,
          fontSize: 13,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          cursor: "pointer",
        }}
      >
        <IFilter size={14} /> Фильтры
      </button>

      <button
        type="button"
        disabled={agentBusy}
        onClick={() => (agentRunning ? agentStopM.mutate() : agentStartM.mutate())}
        style={{
          border: agentRunning ? "none" : "1px solid var(--yellow)",
          background: agentRunning ? "#ffffff15" : "transparent",
          color: agentRunning ? "#F5F1E6" : "var(--yellow)",
          borderRadius: 999,
          padding: "8px 14px",
          fontWeight: 600,
          fontSize: 13,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          cursor: agentBusy ? "not-allowed" : "pointer",
          opacity: agentBusy ? 0.6 : 1,
        }}
      >
        {agentRunning ? (
          <>
            <IPause size={14} /> агент
          </>
        ) : (
          <>
            <ISpark size={14} /> ИИ-агент
          </>
        )}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => (isRunning ? stopM.mutate() : startM.mutate())}
        style={{
          border: "none",
          background: isRunning ? "#ffffff15" : "var(--yellow)",
          color: isRunning ? "#F5F1E6" : "var(--ink)",
          borderRadius: 999,
          padding: "8px 14px",
          fontWeight: 600,
          fontSize: 13,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          cursor: busy ? "not-allowed" : "pointer",
          opacity: busy ? 0.6 : 1,
        }}
      >
        {isRunning ? (
          <>
            <IPause size={14} /> автоотклик
          </>
        ) : (
          <>
            <IPlay size={14} /> автоотклик
          </>
        )}
      </button>
      <button
        type="button"
        onClick={refresh}
        title="обновить (⌘⇧R)"
        style={{
          border: "none",
          background: "#ffffff15",
          color: "#F5F1E6",
          borderRadius: 999,
          width: 34,
          height: 34,
          display: "grid",
          placeItems: "center",
          cursor: "pointer",
        }}
      >
        <IRefresh size={15} style={refreshing ? { animation: "oc-spin 0.6s linear infinite" } : undefined} />
      </button>
    </div>
  );
}
