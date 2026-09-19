"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, Tag } from "@/components/otclick/ui";

type RunStatus =
  | "queued"
  | "discovery"
  | "scoring"
  | "completed"
  | "completed_with_errors"
  | "failed";

type RunResult = {
  id: string;
  status: RunStatus;
  discovery: {
    sources: number;
    fetched: number;
    persisted: number;
    errors: number;
  } | null;
  scoring: {
    found: number;
    scored: number;
    hard_filtered: number;
    archived: number;
    errors: number;
    retryable_errors?: number;
    skipped: number;
    circuit_breaker?: number;
  } | null;
  error: string | null;
};

const FINAL = new Set<RunStatus>(["completed", "completed_with_errors", "failed"]);

const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "в очереди",
  discovery: "поиск вакансий",
  scoring: "оценка вакансий",
  completed: "завершено",
  completed_with_errors: "завершено с ошибками",
  failed: "ошибка запуска",
};

export default function ManualRunPage() {
  const [run, setRun] = useState<RunResult | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const busy = starting || (!!run && !FINAL.has(run.status));

  useEffect(() => {
    if (!run || FINAL.has(run.status)) return;

    let cancelled = false;
    const poll = async () => {
      try {
        const next = await apiFetch<RunResult>(`/api/search-sources/runs/${run.id}`);
        if (!cancelled) {
          setRun(next);
          if (next.status === "failed") {
            setError(next.error || "Ручной цикл завершился с ошибкой");
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Не удалось получить статус запуска");
        }
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [run?.id, run?.status]);

  async function runNow() {
    setStarting(true);
    setError(null);
    try {
      const next = await apiFetch<RunResult>("/api/search-sources/run-now", { method: "POST" });
      setRun(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось запустить поиск");
    } finally {
      setStarting(false);
    }
  }

  const statusTone = useMemo(() => {
    if (!run) return "neutral" as const;
    if (run.status === "completed") return "ok" as const;
    if (run.status === "completed_with_errors") return "warn" as const;
    if (run.status === "failed") return "err" as const;
    return "neutral" as const;
  }, [run]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Card>
        <div style={{ fontSize: 17, fontWeight: 700 }}>Ручной цикл поиска</div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4, maxWidth: 760 }}>
          Ставит discovery и scoring в очередь worker. HTTP-запрос завершается сразу, поэтому длительный поиск больше не зависит от таймаута прокси или браузера. Отправка откликов здесь отсутствует.
        </div>
        <div style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Btn kind="yellow" size="sm" loading={starting} disabled={busy} onClick={runNow}>
            запустить поиск сейчас
          </Btn>
          {run && <Tag tone={statusTone}>{STATUS_LABEL[run.status]}</Tag>}
        </div>
      </Card>

      {run && (
        <Card>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>Результат последнего запуска</div>
          {run.discovery && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Tag tone="neutral">источников {run.discovery.sources}</Tag>
              <Tag tone="neutral">получено {run.discovery.fetched}</Tag>
              <Tag tone="ok">новых/обновлено {run.discovery.persisted}</Tag>
              <Tag tone={run.discovery.errors ? "err" : "neutral"}>discovery errors {run.discovery.errors}</Tag>
            </div>
          )}
          {run.scoring && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: run.discovery ? 8 : 0 }}>
              <Tag tone="neutral">к оценке {run.scoring.found}</Tag>
              <Tag tone="ok">оценено {run.scoring.scored}</Tag>
              <Tag tone="warn">hard filter {run.scoring.hard_filtered}</Tag>
              <Tag tone="neutral">архив {run.scoring.archived}</Tag>
              <Tag tone={run.scoring.errors ? "err" : "neutral"}>score errors {run.scoring.errors}</Tag>
              <Tag tone={run.scoring.retryable_errors ? "warn" : "neutral"}>
                retry later {run.scoring.retryable_errors || 0}
              </Tag>
              <Tag tone="neutral">skipped {run.scoring.skipped}</Tag>
              {!!run.scoring.circuit_breaker && <Tag tone="warn">HH circuit open</Tag>}
            </div>
          )}
          {!run.discovery && !run.scoring && !FINAL.has(run.status) && (
            <div style={{ fontSize: 13, color: "var(--muted)" }}>
              Worker принял задачу. Текущий этап: {STATUS_LABEL[run.status]}.
            </div>
          )}
          {run.status === "scoring" && run.discovery && !run.scoring && (
            <div style={{ marginTop: 8, fontSize: 13, color: "var(--muted)" }}>
              Discovery завершён. Идёт scoring новых вакансий…
            </div>
          )}
        </Card>
      )}

      {error && (
        <Card>
          <div style={{ color: "var(--err)", fontSize: 13 }}>{error}</div>
        </Card>
      )}
    </div>
  );
}
