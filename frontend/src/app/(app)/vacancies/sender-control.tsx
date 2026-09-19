"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, Tag } from "@/components/otclick/ui";

type CurrentJob = {
  id: string;
  hh_vacancy_id: string;
  status: string;
};

type SenderState = {
  desired_state: "paused" | "running" | "stop_after_current";
  safety_interval_seconds: number;
  last_cycle_at: string | null;
  last_outcome: string | null;
  lease_active: boolean;
  runtime_wired: boolean;
  waiting_for_next_batch: number;
  progress: {
    batch_id: string | null;
    batch_status: string | null;
    total: number;
    processed: number;
    queued: number;
    sending: number;
    sent: number;
    failed: number;
    manual_required: number;
    cancelled: number;
    current: CurrentJob | null;
  };
};

const STATE_LABEL: Record<SenderState["desired_state"], string> = {
  paused: "пауза",
  running: "готов к обработке",
  stop_after_current: "стоп после текущей",
};

export default function SenderControl() {
  const [state, setState] = useState<SenderState | null>(null);
  const [intervalValue, setIntervalValue] = useState("10");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await apiFetch<SenderState>("/api/send-queue/control");
      setState(next);
      setIntervalValue(String(next.safety_interval_seconds));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить состояние очереди");
    }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function action(
    name: "resume" | "pause" | "stop_after_current" | "configure",
  ) {
    setBusy(true);
    try {
      const seconds = Number(intervalValue);
      const payload: Record<string, unknown> = { action: name };
      if (name === "configure" || name === "resume") {
        if (!Number.isInteger(seconds) || seconds < 0 || seconds > 300) {
          throw new Error("Интервал должен быть целым числом от 0 до 300 секунд");
        }
        payload.safety_interval_seconds = seconds;
      }
      const next = await apiFetch<SenderState>("/api/send-queue/control", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setState(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить режим очереди");
    } finally {
      setBusy(false);
    }
  }

  if (!state) {
    return (
      <Card>
        <div style={{ fontSize: 14, color: "var(--muted)" }}>Загрузка состояния очереди…</div>
        {error && <div style={{ color: "var(--err)", fontSize: 12, marginTop: 8 }}>{error}</div>}
      </Card>
    );
  }

  const p = state.progress;
  const pct = p.total > 0 ? Math.round((p.processed / p.total) * 100) : 0;

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>Очередь отправки</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
            Snapshot batch: вакансии, добавленные после Resume, попадут только в следующий batch.
          </div>
        </div>
        <Tag tone={state.desired_state === "running" ? "yellow" : "neutral"} dot>
          {STATE_LABEL[state.desired_state]}
        </Tag>
        <Tag tone={state.runtime_wired ? "warn" : "ok"} dot>
          {state.runtime_wired ? "runtime подключён" : "runtime отключён"}
        </Tag>
      </div>

      {!state.runtime_wired && (
        <div
          style={{
            marginTop: 12,
            padding: "10px 12px",
            borderRadius: 12,
            background: "var(--bg-deep)",
            fontSize: 12,
          }}
        >
          Кнопки ниже меняют только durable control-state. Sender не запущен в worker_main и реальные HH-отклики не выполняются.
        </div>
      )}

      <div style={{ marginTop: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13 }}>
          <span>batch progress</span>
          <strong>{p.processed}/{p.total} · {pct}%</strong>
        </div>
        <div style={{ height: 8, borderRadius: 999, background: "var(--line)", overflow: "hidden", marginTop: 6 }}>
          <div style={{ width: `${pct}%`, height: "100%", background: "var(--ink)" }} />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
          <Tag tone="neutral">в очереди {p.queued}</Tag>
          <Tag tone="ok">отправлено {p.sent}</Tag>
          <Tag tone="err">ошибки {p.failed}</Tag>
          <Tag tone="warn">ручные {p.manual_required}</Tag>
          <Tag tone="neutral">отменено {p.cancelled}</Tag>
          {state.waiting_for_next_batch > 0 && (
            <Tag tone="yellow">следующий batch +{state.waiting_for_next_batch}</Tag>
          )}
        </div>
      </div>

      {p.current && (
        <div style={{ marginTop: 12, fontSize: 12 }}>
          Сейчас: HH #{p.current.hh_vacancy_id} · {p.current.status}
          {state.lease_active ? " · lease active" : ""}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 14 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
          интервал
          <input
            type="number"
            min={0}
            max={300}
            step={1}
            value={intervalValue}
            onChange={(event) => setIntervalValue(event.target.value)}
            style={{ width: 72, padding: "7px 8px", border: "1px solid var(--line)", borderRadius: 10 }}
          />
          сек
        </label>
        <Btn kind="ghost" size="sm" disabled={busy} onClick={() => action("configure")}>
          сохранить
        </Btn>
        <Btn kind="yellow" size="sm" disabled={busy || state.desired_state === "running"} onClick={() => action("resume")}>
          Resume
        </Btn>
        <Btn kind="ghost" size="sm" disabled={busy || state.desired_state === "paused"} onClick={() => action("pause")}>
          Pause
        </Btn>
        <Btn
          kind="ghost"
          size="sm"
          disabled={busy || state.desired_state === "paused"}
          onClick={() => action("stop_after_current")}
        >
          Stop after current
        </Btn>
      </div>

      {(state.last_outcome || state.last_cycle_at) && (
        <div style={{ marginTop: 10, color: "var(--muted)", fontSize: 11 }}>
          {state.last_outcome ? `последний результат: ${state.last_outcome}` : ""}
          {state.last_cycle_at ? ` · ${new Date(state.last_cycle_at).toLocaleString("ru-RU")}` : ""}
        </div>
      )}
      {error && <div style={{ color: "var(--err)", fontSize: 12, marginTop: 8 }}>{error}</div>}
    </Card>
  );
}
