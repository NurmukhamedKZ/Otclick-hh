"use client";

import { Btn, Card, EmptyState, Tag } from "@/components/otclick/ui";
import { apiFetch } from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

type SourceStats = {
  runs?: number;
  fetched?: number;
  persisted?: number;
  skipped_applied?: number;
  errors?: number;
};

type LastRun = {
  checked_at?: string;
  fetched?: number;
  persisted?: number;
  skipped_applied?: number;
  overlap_found?: boolean;
  error?: string | null;
};

type SearchSource = {
  id: string;
  name: string;
  source_type: string;
  enabled: boolean;
  last_error: string | null;
  cursor: {
    stats?: SourceStats;
    last_run?: LastRun;
  };
};

type MaintenanceStatus = {
  stale_scores: number;
  stale_covers_safe_to_regenerate: number;
  score_limit: number;
  cover_limit: number;
  protected_states: string[];
};

type CalibrationBand = {
  label: string;
  min_score: number;
  max_score: number;
  positive: number;
  rejected: number;
  total: number;
};

type CalibrationDecision = {
  pipeline_id: string;
  hh_vacancy_id: string;
  title: string;
  employer_name: string | null;
  lifecycle_status: string;
  decision: "positive" | "rejected";
  score: number | null;
  score_stale: boolean | null;
  user_decision_reason: string | null;
  discovered_at: string;
};

type CalibrationReport = {
  reviewed: number;
  positive: number;
  rejected: number;
  with_score: number;
  stale_scores: number;
  fresh_scored_decisions: number;
  average_positive_score: number | null;
  average_rejected_score: number | null;
  bands: CalibrationBand[];
  decisions: CalibrationDecision[];
};

type RescoreResult = {
  matched_stale: number;
  requeued: number;
  scoring: {
    found: number;
    scored: number;
    hard_filtered: number;
    archived: number;
    errors: number;
    skipped: number;
  };
};

type CoverResult = {
  matched_stale: number;
  regenerated: number;
  errors: Array<{ pipeline_id: string; error: string }>;
};

export default function SourceStatsPage() {
  const [rows, setRows] = useState<SearchSource[] | null>(null);
  const [maintenance, setMaintenance] = useState<MaintenanceStatus | null>(null);
  const [calibration, setCalibration] = useState<CalibrationReport | null>(null);
  const [busy, setBusy] = useState<"score" | "cover" | null>(null);
  const [maintenanceMessage, setMaintenanceMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [sources, state, calibrationState] = await Promise.all([
        apiFetch<SearchSource[]>("/api/search-sources"),
        apiFetch<MaintenanceStatus>("/api/vacancies/maintenance"),
        apiFetch<CalibrationReport>("/api/vacancies/calibration"),
      ]);
      setRows(sources);
      setMaintenance(state);
      setCalibration(calibrationState);
      setError(null);
    } catch (err) {
      setRows([]);
      setCalibration(null);
      setError(err instanceof Error ? err.message : "Не удалось загрузить статистику");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function rescoreStale() {
    setBusy("score");
    setError(null);
    setMaintenanceMessage(null);
    try {
      const result = await apiFetch<RescoreResult>("/api/vacancies/maintenance/rescore-stale", {
        method: "POST",
      });
      setMaintenanceMessage(
        `Score: stale ${result.matched_stale}, пересчитано ${result.scoring.scored}, hard filter ${result.scoring.hard_filtered}, errors ${result.scoring.errors}.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось пересчитать stale score");
    } finally {
      setBusy(null);
    }
  }

  async function regenerateStaleCovers() {
    setBusy("cover");
    setError(null);
    setMaintenanceMessage(null);
    try {
      const result = await apiFetch<CoverResult>(
        "/api/vacancies/maintenance/regenerate-stale-covers",
        { method: "POST" },
      );
      setMaintenanceMessage(
        `Письма: stale ${result.matched_stale}, перегенерировано ${result.regenerated}, errors ${result.errors.length}.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось перегенерировать stale письма");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Card>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 17, fontWeight: 700 }}>Статистика и актуальность</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
              Discovery stats копятся по источникам. Stale означает, что профиль, правила, модель, резюме или содержимое вакансии изменились после расчёта.
            </div>
          </div>
          <Btn kind="ghost" size="sm" onClick={load}>обновить</Btn>
        </div>
      </Card>

      {calibration && (
        <Card>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Калибровка score по решениям</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 5 }}>
            Только явные решения пользователя. Stale score виден в деталях, но не участвует в средних и диапазонах.
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
            <Tag tone="neutral">reviewed {calibration.reviewed}</Tag>
            <Tag tone="ok">positive {calibration.positive}</Tag>
            <Tag tone={calibration.rejected ? "warn" : "neutral"}>rejected {calibration.rejected}</Tag>
            <Tag tone={calibration.stale_scores ? "warn" : "neutral"}>stale {calibration.stale_scores}</Tag>
          </div>
          <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
            Средний score: выбранные {calibration.average_positive_score ?? "—"} · отклонённые {calibration.average_rejected_score ?? "—"}. Свежих scored decisions: {calibration.fresh_scored_decisions}.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 8, marginTop: 12 }}>
            {calibration.bands.map((band) => (
              <div
                key={band.label}
                style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 10 }}
              >
                <div style={{ fontSize: 13, fontWeight: 700 }}>{band.label}</div>
                <div style={{ fontSize: 12, marginTop: 5 }}>выбрано {band.positive}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>отклонено {band.rejected}</div>
              </div>
            ))}
          </div>
          {calibration.decisions.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>Последние решения</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 7, marginTop: 7 }}>
                {calibration.decisions.slice(0, 8).map((item) => (
                  <div key={item.pipeline_id} style={{ fontSize: 12 }}>
                    <strong>{item.score ?? "—"}</strong>{item.score_stale ? " stale" : ""} · {item.decision === "positive" ? "выбрано" : "отклонено"} · {item.title}
                    {item.employer_name ? ` · ${item.employer_name}` : ""}
                    {item.user_decision_reason ? (
                      <div style={{ color: "var(--muted)", marginTop: 2 }}>{item.user_decision_reason}</div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {maintenance && (
        <Card>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Maintenance</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
            <Tag tone={maintenance.stale_scores ? "warn" : "ok"}>stale score {maintenance.stale_scores}</Tag>
            <Tag tone={maintenance.stale_covers_safe_to_regenerate ? "warn" : "ok"}>
              stale AI drafts {maintenance.stale_covers_safe_to_regenerate}
            </Tag>
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 9 }}>
            Score пачкой меняется только для scored/review/score_error. Письма — только для letter_draft, которые пользователь ещё не редактировал. Approved/queued/selected/hold/rejected/sent защищены.
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
            <Btn
              kind="yellow"
              size="sm"
              loading={busy === "score"}
              disabled={busy !== null || maintenance.stale_scores === 0}
              onClick={rescoreStale}
            >
              пересчитать stale score · {maintenance.stale_scores}
            </Btn>
            <Btn
              kind="ghost"
              size="sm"
              loading={busy === "cover"}
              disabled={busy !== null || maintenance.stale_covers_safe_to_regenerate === 0}
              onClick={regenerateStaleCovers}
            >
              перегенерировать stale AI drafts · {maintenance.stale_covers_safe_to_regenerate}
            </Btn>
          </div>
          {maintenanceMessage && (
            <div style={{ fontSize: 12, marginTop: 9 }}>{maintenanceMessage}</div>
          )}
        </Card>
      )}

      {error && <div style={{ color: "var(--err)", fontSize: 12 }}>{error}</div>}

      {rows === null ? (
        <Card><div style={{ fontSize: 13, color: "var(--muted)" }}>Загрузка…</div></Card>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<span aria-hidden>∅</span>}
            title="Нет источников"
            description="Сначала добавьте Search URL в разделе Источники."
          />
        </Card>
      ) : (
        rows.map((row) => {
          const stats = row.cursor?.stats ?? {};
          const last = row.cursor?.last_run ?? {};
          const runs = stats.runs ?? 0;
          const fetched = stats.fetched ?? 0;
          const persisted = stats.persisted ?? 0;
          const yieldPct = fetched > 0 ? Math.round((persisted / fetched) * 100) : 0;
          return (
            <Card key={row.id}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <strong style={{ fontSize: 14 }}>{row.name}</strong>
                <Tag tone={row.enabled ? "ok" : "neutral"}>{row.enabled ? "включён" : "выключен"}</Tag>
                <Tag tone="neutral">{row.source_type}</Tag>
                {(stats.errors ?? 0) > 0 && <Tag tone="err">errors {stats.errors}</Tag>}
              </div>

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <Tag tone="neutral">runs {runs}</Tag>
                <Tag tone="neutral">fetched {fetched}</Tag>
                <Tag tone="ok">persisted {persisted}</Tag>
                <Tag tone="neutral">yield {yieldPct}%</Tag>
                <Tag tone="neutral">already applied {stats.skipped_applied ?? 0}</Tag>
              </div>

              {runs > 0 && (
                <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
                  Последний run: fetched {last.fetched ?? 0}, persisted {last.persisted ?? 0}, skipped {last.skipped_applied ?? 0}
                  {last.overlap_found === false ? " · overlap не найден" : ""}
                </div>
              )}
              {(last.error || row.last_error) && (
                <div style={{ marginTop: 7, fontSize: 12, color: "var(--err)", wordBreak: "break-word" }}>
                  {last.error || row.last_error}
                </div>
              )}
            </Card>
          );
        })
      )}
    </div>
  );
}
