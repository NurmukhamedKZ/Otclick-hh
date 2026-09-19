"use client";

import { Btn, Card, EmptyState, Tag } from "@/components/otclick/ui";
import { apiFetch } from "@/lib/api";
import { useCallback, useEffect, useMemo, useState } from "react";

type Vacancy = {
  id: string;
  hh_vacancy_id: string;
  title: string;
  employer_name: string | null;
  score: number | null;
  status: string;
  approved_at: string | null;
  cover_letter_draft: string | null;
};

type BulkResult = {
  results: Array<{
    pipeline_id: string;
    status: "queued" | "error";
    job_id: string | null;
    error: string | null;
  }>;
  queued: number;
  errors: number;
};

export default function BulkQueuePage() {
  const [rows, setRows] = useState<Vacancy[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkResult | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<Vacancy[]>("/api/vacancies?status=approved&limit=100&offset=0");
      setRows(data);
      setSelected(new Set());
      setError(null);
    } catch (err) {
      setRows([]);
      setError(err instanceof Error ? err.message : "Не удалось загрузить approved вакансии");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const allSelected = useMemo(
    () => Boolean(rows?.length) && selected.size === rows?.length,
    [rows, selected],
  );

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((current) => {
      if (rows && current.size === rows.length) return new Set();
      return new Set((rows ?? []).map((row) => row.id));
    });
  }

  async function queueSelected() {
    if (selected.size === 0) return;
    setBusy(true);
    try {
      const response = await apiFetch<BulkResult>("/api/send-queue/bulk", {
        method: "POST",
        body: JSON.stringify({ pipeline_ids: Array.from(selected) }),
      });
      setResult(response);
      const queuedIds = new Set(
        response.results.filter((item) => item.status === "queued").map((item) => item.pipeline_id),
      );
      setRows((current) => (current ?? []).filter((row) => !queuedIds.has(row.id)));
      setSelected((current) => new Set(Array.from(current).filter((id) => !queuedIds.has(id))));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось поставить вакансии в очередь");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Card>
        <div style={{ fontSize: 17, fontWeight: 700 }}>Пакетная постановка в очередь</div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
          Здесь показываются только вакансии со статусом approved. Пакетная операция не одобряет письмо и не отправляет отклик в HH.
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          <Btn kind="ghost" size="sm" onClick={toggleAll} disabled={!rows?.length}>
            {allSelected ? "снять все" : "выбрать все"}
          </Btn>
          <Btn kind="yellow" size="sm" onClick={queueSelected} disabled={busy || selected.size === 0}>
            в очередь · {selected.size}
          </Btn>
          <Btn kind="ghost" size="sm" onClick={load} disabled={busy}>обновить</Btn>
        </div>
      </Card>

      {result && (
        <Card>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Tag tone="ok">queued {result.queued}</Tag>
            <Tag tone={result.errors ? "err" : "neutral"}>errors {result.errors}</Tag>
          </div>
          {result.errors > 0 && (
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 5 }}>
              {result.results.filter((item) => item.status === "error").map((item) => (
                <div key={item.pipeline_id} style={{ fontSize: 12, color: "var(--err)" }}>
                  {item.pipeline_id}: {item.error || "unknown error"}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {error && <div style={{ fontSize: 12, color: "var(--err)" }}>{error}</div>}

      {rows === null ? (
        <Card><div style={{ fontSize: 13, color: "var(--muted)" }}>Загрузка…</div></Card>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<span aria-hidden>✓</span>}
            title="Нет approved вакансий"
            description="Сначала выберите вакансию, проверьте письмо и отдельно одобрите точный текст."
          />
        </Card>
      ) : (
        rows.map((row) => (
          <Card key={row.id}>
            <label style={{ display: "flex", gap: 12, alignItems: "flex-start", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={selected.has(row.id)}
                onChange={() => toggle(row.id)}
                style={{ marginTop: 4, width: 18, height: 18 }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 14 }}>{row.title}</strong>
                  <Tag tone="ok">approved</Tag>
                  {row.score !== null && <Tag tone="neutral">score {row.score}</Tag>}
                </div>
                <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                  {row.employer_name || "работодатель не указан"} · HH #{row.hh_vacancy_id}
                </div>
                {row.approved_at && (
                  <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
                    одобрено {new Date(row.approved_at).toLocaleString("ru-RU")}
                  </div>
                )}
              </div>
            </label>
          </Card>
        ))
      )}
    </div>
  );
}
