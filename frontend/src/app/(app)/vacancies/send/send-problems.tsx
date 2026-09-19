"use client";

import { Btn, Card, EmptyState, Tag } from "@/components/otclick/ui";
import { apiFetch } from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

type SendJob = {
  id: string;
  vacancy_pipeline_id: string;
  hh_vacancy_id: string;
  batch_id: string | null;
  status: "failed" | "manual_required";
  attempts: number;
  last_error: string | null;
  queued_at: string;
};

export default function SendProblems() {
  const [rows, setRows] = useState<SendJob[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<SendJob[]>(
        "/api/send-queue?status=failed&status=manual_required&limit=50",
      );
      setRows(data);
      setError(null);
    } catch (err) {
      setRows([]);
      setError(err instanceof Error ? err.message : "Не удалось загрузить ошибки отправки");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function reset(row: SendJob) {
    setBusyId(row.id);
    try {
      await apiFetch(`/api/send-queue/${row.vacancy_pipeline_id}/reset`, { method: "POST" });
      setRows((current) => (current ?? []).filter((item) => item.id !== row.id));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сбросить job");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>Требуют решения</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
            Reset не повторяет отклик: job отменяется, а вакансия возвращается в approved для нового явного решения.
          </div>
        </div>
        <Btn kind="ghost" size="sm" onClick={load}>обновить</Btn>
      </div>

      {rows === null ? (
        <div style={{ marginTop: 14, fontSize: 13, color: "var(--muted)" }}>Загрузка…</div>
      ) : rows.length === 0 ? (
        <div style={{ marginTop: 14 }}>
          <EmptyState
            icon={<span aria-hidden>✓</span>}
            title="Нет failed/manual jobs"
            description="Проблемные отправки появятся здесь."
          />
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
          {rows.map((row) => (
            <div
              key={row.id}
              style={{
                border: "1px solid var(--line)",
                borderRadius: 12,
                padding: 12,
                display: "flex",
                gap: 10,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <div style={{ flex: 1, minWidth: 190 }}>
                <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 13 }}>HH #{row.hh_vacancy_id}</strong>
                  <Tag tone={row.status === "failed" ? "err" : "warn"}>{row.status}</Tag>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>attempts {row.attempts}</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 5, wordBreak: "break-word" }}>
                  {row.last_error || "без текста ошибки"}
                </div>
              </div>
              <Btn kind="ghost" size="sm" disabled={busyId === row.id} onClick={() => reset(row)}>
                вернуть в approved
              </Btn>
            </div>
          ))}
        </div>
      )}
      {error && <div style={{ color: "var(--err)", fontSize: 12, marginTop: 10 }}>{error}</div>}
    </Card>
  );
}
