"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, EmptyState, Skeleton, Tag } from "@/components/otclick/ui";
import { IRefresh, ISettings } from "@/components/otclick/icons";

type Rule = {
  id: string;
  version: number;
  name: string;
  action: "hard_reject" | "scoring_preference";
  match: Record<string, string[]>;
  instruction: string;
  active: boolean;
  deleted_at?: string | null;
  superseded_by_rule_id?: string | null;
};
type RescoreResult = {
  rule_id: string;
  rule_version: number;
  matched_rescorable: number;
  queued_for_rescore: number;
  protected_statuses_unchanged: string[];
};
type ArchiveImpactResult = {
  rule_id: string;
  rule_version: number;
  matched_archivable: number;
  archived: number;
  skipped: number;
};
type Proposal = { id: string; impact_preview?: { matched_count?: number } };

function matchTerms(match: Record<string, string[]>) {
  return Object.entries(match).flatMap(([field, values]) => (values ?? []).map((value) => ({ field, value })));
}

export default function RuleManagementPage() {
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRules(await apiFetch<Rule[]>("/api/selection-rules"));
      setError(null);
    } catch (err) {
      setRules([]);
      setError(err instanceof Error ? err.message : "Не удалось загрузить правила");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function toggle(rule: Rule) {
    setBusyId(rule.id); setMessage(null); setError(null);
    try {
      const next = await apiFetch<Rule>(`/api/selection-rules/${rule.id}`, {
        method: "PATCH",
        body: JSON.stringify({ active: !rule.active }),
      });
      setRules((current) => (current ?? []).map((item) => item.id === rule.id ? next : item));
      setMessage(next.active ? `Правило v${next.version} включено.` : `Правило v${next.version} выключено.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить правило");
    } finally { setBusyId(null); }
  }

  async function rescore(rule: Rule) {
    setBusyId(rule.id); setMessage(null); setError(null);
    try {
      const result = await apiFetch<RescoreResult>(`/api/selection-rules/${rule.id}/rescore-impact`, { method: "POST" });
      setMessage(`На пересчёт поставлено ${result.queued_for_rescore} из ${result.matched_rescorable}. Ручные решения не изменены.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось поставить вакансии на пересчёт");
    } finally { setBusyId(null); }
  }

  async function regenerate(rule: Rule) {
    setBusyId(rule.id); setMessage(null); setError(null);
    try {
      const proposal = await apiFetch<Proposal>(`/api/selection-rules/${rule.id}/regenerate`, { method: "POST" });
      const matched = proposal.impact_preview?.matched_count ?? 0;
      setMessage(`Создано новое предложение правила (${proposal.id}). Затронет вакансий: ${matched}. Проверь и одобри его на странице предложений правил.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось перегенерировать правило");
    } finally { setBusyId(null); }
  }

  async function archiveImpact(rule: Rule) {
    if (!window.confirm(`Архивировать без анализа все неразобранные вакансии, подходящие под правило v${rule.version}?`)) return;
    setBusyId(rule.id); setMessage(null); setError(null);
    try {
      const result = await apiFetch<ArchiveImpactResult>(`/api/selection-rules/${rule.id}/archive-impact`, { method: "POST" });
      setMessage(`По правилу v${rule.version}: найдено ${result.matched_archivable}, архивировано без анализа ${result.archived}, пропущено ${result.skipped}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось архивировать затронутые вакансии");
    } finally { setBusyId(null); }
  }

  async function removeRule(rule: Rule) {
    if (!window.confirm(`Удалить правило v${rule.version} «${rule.name}»? История старых решений сохранится.`)) return;
    setBusyId(rule.id); setMessage(null); setError(null);
    try {
      const next = await apiFetch<Rule>(`/api/selection-rules/${rule.id}`, { method: "DELETE" });
      setRules((current) => (current ?? []).map((item) => item.id === rule.id ? next : item));
      setMessage(`Правило v${rule.version} удалено из активного отбора. История сохранена.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить правило");
    } finally { setBusyId(null); }
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 750 }}>Управление правилами</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
              Правила версионируются. Удаление не стирает историю автоматических решений.
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <Btn kind="ghost" size="sm" icon={<IRefresh size={14} />} onClick={load}>обновить</Btn>
        </div>
      </Card>

      {message && <div style={{ padding: "10px 14px", borderRadius: 12, background: "var(--sage-soft)", fontSize: 12 }}>{message}</div>}
      {error && <div style={{ padding: "10px 14px", borderRadius: 12, background: "var(--coral-soft)", color: "var(--err)", fontSize: 12 }}>{error}</div>}

      {rules === null ? (
        <Card><Skeleton h={110} count={4} /></Card>
      ) : rules.length === 0 ? (
        <Card><EmptyState icon={<ISettings size={22} />} title="Одобренных правил пока нет" description="Сначала отклони вакансию с причиной и явно одобри предложение правила." /></Card>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {rules.map((rule) => {
            const deleted = Boolean(rule.deleted_at);
            const superseded = Boolean(rule.superseded_by_rule_id);
            return (
              <Card key={rule.id}>
                <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                  <div style={{ fontWeight: 750, fontSize: 14 }}>{rule.name}</div>
                  <Tag tone="neutral">v{rule.version}</Tag>
                  {deleted ? <Tag tone="coral">удалено</Tag> : superseded ? <Tag tone="neutral">заменено новой версией</Tag> : <Tag tone={rule.active ? "ok" : "neutral"}>{rule.active ? "включено" : "выключено"}</Tag>}
                  <Tag tone={rule.action === "hard_reject" ? "coral" : "neutral"}>{rule.action === "hard_reject" ? "жёсткий отказ" : "scoring preference"}</Tag>
                </div>

                <div style={{ fontSize: 13, marginTop: 8 }}>{rule.instruction}</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                  {matchTerms(rule.match).map(({ field, value }) => <Tag key={`${field}:${value}`} tone="neutral">{field}: {value}</Tag>)}
                </div>

                {!deleted && (
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
                    <Btn kind={rule.active ? "ghost" : "primary"} size="sm" loading={busyId === rule.id} onClick={() => toggle(rule)}>{rule.active ? "выключить" : "включить"}</Btn>
                    <Btn kind="yellow" size="sm" disabled={busyId === rule.id} onClick={() => regenerate(rule)}>перегенерировать</Btn>
                    <Btn kind="ghost" size="sm" disabled={busyId === rule.id} onClick={() => rescore(rule)}>пересчитать затронутые</Btn>
                    {rule.action === "hard_reject" && (
                      <Btn kind="soft" size="sm" disabled={busyId === rule.id} onClick={() => archiveImpact(rule)}>архивировать затронутые</Btn>
                    )}
                    <Btn kind="coral" size="sm" disabled={busyId === rule.id} onClick={() => removeRule(rule)}>удалить</Btn>
                  </div>
                )}
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 7 }}>
                  Пересчёт может вернуть предыдущие auto-reject в очередь. «Архивировать затронутые» не запускает LLM и не создаёт новые правила.
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
