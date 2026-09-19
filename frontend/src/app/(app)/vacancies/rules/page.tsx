"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, EmptyState, Skeleton, Tag } from "@/components/otclick/ui";
import { IRefresh, ISpark } from "@/components/otclick/icons";

type Proposal = {
  id: string;
  source_vacancy_id: string | null;
  source_reason: string;
  decision: "rule" | "change" | "no_generalization";
  proposed_rule: {
    name?: string;
    action?: "hard_reject" | "scoring_preference";
    match?: {
      title_any?: string[];
      employer_any?: string[];
      description_any?: string[];
    };
    instruction?: string;
    replace_rule_id?: string | null;
  } | null;
  explanation: string | null;
  impact_preview: {
    checked?: number;
    matched_count?: number;
    matched?: { id: string; title?: string; employer_name?: string; status?: string; score?: number | null }[];
    truncated?: boolean;
  };
  status: "pending" | "approved" | "rejected";
  created_at: string;
};

type Rule = {
  id: string;
  version: number;
  name: string;
  action: "hard_reject" | "scoring_preference";
  match: Record<string, string[]>;
  instruction: string;
  active: boolean;
};

type RejectedVacancy = {
  id: string;
  title: string;
  employer_name: string | null;
  status: string;
  user_decision_reason: string | null;
  score: number | null;
};

function actionLabel(action?: string) {
  if (action === "hard_reject") return "жёсткий отказ";
  if (action === "scoring_preference") return "учитывать в оценке";
  return "—";
}

function matchTerms(match?: Record<string, string[]>) {
  if (!match) return [];
  return Object.entries(match).flatMap(([field, values]) =>
    (values ?? []).map((value) => ({ field, value })),
  );
}

export default function RulesPage() {
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [rejected, setRejected] = useState<RejectedVacancy[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, r, v] = await Promise.all([
        apiFetch<Proposal[]>("/api/selection-rules/proposals"),
        apiFetch<Rule[]>("/api/selection-rules"),
        apiFetch<RejectedVacancy[]>("/api/vacancies?status=rejected_by_user&limit=100&offset=0"),
      ]);
      setProposals(p);
      setRules(r);
      setRejected(v);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить правила");
      setProposals([]);
      setRules([]);
      setRejected([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pending = useMemo(
    () => (proposals ?? []).filter((proposal) => proposal.status === "pending"),
    [proposals],
  );
  const proposalVacancyIds = useMemo(
    () => new Set((proposals ?? []).map((proposal) => proposal.source_vacancy_id).filter(Boolean)),
    [proposals],
  );
  const candidates = useMemo(
    () => (rejected ?? []).filter((vacancy) => vacancy.user_decision_reason && !proposalVacancyIds.has(vacancy.id)),
    [rejected, proposalVacancyIds],
  );

  async function analyze(vacancyId: string) {
    setBusyId(vacancyId);
    setError(null);
    try {
      await apiFetch(`/api/selection-rules/proposals/from-vacancy/${vacancyId}`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сформировать предложение правила");
    } finally {
      setBusyId(null);
    }
  }

  async function resolve(proposalId: string, approve: boolean) {
    setBusyId(proposalId);
    setError(null);
    try {
      await apiFetch(`/api/selection-rules/proposals/${proposalId}/resolve`, {
        method: "POST",
        body: JSON.stringify({ approve }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось обработать предложение");
    } finally {
      setBusyId(null);
    }
  }

  const loading = proposals === null || rules === null || rejected === null;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 750 }}>Правила отбора</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
              Причина отказа → предложение → impact preview → твоё approval. Без approval scoring не меняется.
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <Btn kind="ghost" size="sm" icon={<IRefresh size={14} />} onClick={load}>
            обновить
          </Btn>
        </div>
      </Card>

      {error && (
        <div style={{ padding: "10px 14px", borderRadius: 12, background: "var(--coral-soft)", color: "var(--err)", fontSize: 12 }}>
          {error}
        </div>
      )}

      {loading ? (
        <Card><Skeleton h={90} count={5} /></Card>
      ) : (
        <>
          <Card>
            <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Новые причины отказа</div>
            {candidates.length === 0 ? (
              <div style={{ fontSize: 12, color: "var(--muted)" }}>
                Нет новых причин для анализа. Причина сохраняется при ручном отклонении вакансии.
              </div>
            ) : (
              <div style={{ display: "grid", gap: 10 }}>
                {candidates.map((vacancy) => (
                  <div key={vacancy.id} style={{ padding: 12, borderRadius: 14, background: "var(--bg-deep)" }}>
                    <div style={{ fontWeight: 700, fontSize: 13 }}>{vacancy.title}</div>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
                      {[vacancy.employer_name, vacancy.score == null ? null : `score ${vacancy.score}`].filter(Boolean).join(" · ")}
                    </div>
                    <div style={{ fontSize: 13, marginTop: 8 }}>«{vacancy.user_decision_reason}»</div>
                    <div style={{ marginTop: 9 }}>
                      <Btn kind="yellow" size="sm" loading={busyId === vacancy.id} onClick={() => analyze(vacancy.id)}>
                        проанализировать как правило
                      </Btn>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Ожидают решения</div>
            {pending.length === 0 ? (
              <EmptyState icon={<ISpark size={22} />} title="Нет предложений" description="LLM ничего не активирует самостоятельно." />
            ) : (
              <div style={{ display: "grid", gap: 12 }}>
                {pending.map((proposal) => {
                  const rule = proposal.proposed_rule;
                  const impact = proposal.impact_preview ?? {};
                  return (
                    <div key={proposal.id} style={{ border: "1px solid var(--line)", borderRadius: 16, padding: 14 }}>
                      <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                        <Tag tone={proposal.decision === "no_generalization" ? "neutral" : "yellow"}>
                          {proposal.decision === "no_generalization" ? "не обобщать" : proposal.decision === "change" ? "изменить правило" : "новое правило"}
                        </Tag>
                        {rule?.action && <Tag tone={rule.action === "hard_reject" ? "coral" : "neutral"}>{actionLabel(rule.action)}</Tag>}
                        {typeof impact.matched_count === "number" && (
                          <Tag tone="neutral">затронет {impact.matched_count} / {impact.checked ?? 0}</Tag>
                        )}
                      </div>

                      <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>Исходная причина</div>
                      <div style={{ fontSize: 13, marginTop: 3 }}>«{proposal.source_reason}»</div>

                      {rule && (
                        <>
                          <div style={{ fontSize: 15, fontWeight: 750, marginTop: 12 }}>{rule.name}</div>
                          <div style={{ fontSize: 13, marginTop: 4 }}>{rule.instruction}</div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                            {matchTerms(rule.match).map(({ field, value }) => (
                              <Tag key={`${field}:${value}`} tone="neutral">{field}: {value}</Tag>
                            ))}
                          </div>
                        </>
                      )}

                      {proposal.explanation && (
                        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 10 }}>{proposal.explanation}</div>
                      )}

                      {(impact.matched ?? []).length > 0 && (
                        <details style={{ marginTop: 10 }}>
                          <summary style={{ cursor: "pointer", fontSize: 12, fontWeight: 650 }}>
                            показать затронутые вакансии
                          </summary>
                          <div style={{ display: "grid", gap: 5, marginTop: 7 }}>
                            {(impact.matched ?? []).map((row) => (
                              <div key={row.id} style={{ fontSize: 12 }}>
                                {row.title || row.id}{row.employer_name ? ` · ${row.employer_name}` : ""}{row.score == null ? "" : ` · score ${row.score}`}
                              </div>
                            ))}
                            {impact.truncated && <div style={{ fontSize: 11, color: "var(--muted)" }}>Список сокращён.</div>}
                          </div>
                        </details>
                      )}

                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
                        <Btn kind="primary" size="sm" loading={busyId === proposal.id} onClick={() => resolve(proposal.id, true)}>
                          {proposal.decision === "no_generalization" ? "согласен: не обобщать" : "одобрить правило"}
                        </Btn>
                        <Btn kind="ghost" size="sm" disabled={busyId === proposal.id} onClick={() => resolve(proposal.id, false)}>
                          отклонить предложение
                        </Btn>
                      </div>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 7 }}>
                        Approval влияет только на последующие оценки. Старые ручные решения автоматически не меняются.
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          <Card>
            <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Активные правила</div>
            {(rules ?? []).filter((rule) => rule.active).length === 0 ? (
              <div style={{ fontSize: 12, color: "var(--muted)" }}>Пока нет одобренных правил.</div>
            ) : (
              <div style={{ display: "grid", gap: 10 }}>
                {(rules ?? []).filter((rule) => rule.active).map((rule) => (
                  <div key={rule.id} style={{ padding: 12, borderRadius: 14, background: "var(--bg-deep)" }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                      <div style={{ fontWeight: 700, fontSize: 13 }}>{rule.name}</div>
                      <Tag tone="neutral">v{rule.version}</Tag>
                      <Tag tone={rule.action === "hard_reject" ? "coral" : "neutral"}>{actionLabel(rule.action)}</Tag>
                    </div>
                    <div style={{ fontSize: 13, marginTop: 6 }}>{rule.instruction}</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 7 }}>
                      {matchTerms(rule.match).map(({ field, value }) => (
                        <Tag key={`${field}:${value}`} tone="neutral">{field}: {value}</Tag>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
