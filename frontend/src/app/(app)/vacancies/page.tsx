"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, EmptyState, Skeleton, Tag } from "@/components/otclick/ui";
import { IExternal, IList, IRefresh } from "@/components/otclick/icons";
import CoverLetterEditor from "./cover-letter-editor";
import styles from "./page.module.css";

const PAGE_SIZE = 25;
const ARCHIVABLE = new Set(["discovered", "scoring", "scored", "review", "score_error"]);

type VacancySource = { id: string; name: string; source_type: string };
type MatchEvidence = { field: string; term: string };
type AutoReject = {
  type: "rule" | "system";
  rule_id?: string;
  version?: number;
  name?: string;
  instruction?: string;
  reason?: string;
  matches?: MatchEvidence[];
};
type ScoreDetails = {
  components?: Record<string, number>;
  pros?: string[];
  risks?: string[];
  unknowns?: string[];
  confidence?: number;
  hard_filter?: boolean;
  error?: string;
  auto_rejects?: AutoReject[];
};
type Vacancy = {
  id: string;
  hh_vacancy_id: string;
  vacancy_url: string | null;
  title: string;
  employer_name: string | null;
  area_name: string | null;
  salary: Record<string, unknown> | null;
  discovered_at: string;
  description: string | null;
  status: string;
  score: number | null;
  score_details: ScoreDetails | null;
  score_explanation: string | null;
  hard_filter_reason: string | null;
  auto_reject_details: AutoReject[] | null;
  user_decision_reason: string | null;
  cover_letter_draft: string | null;
  cover_letter_meta: Record<string, unknown>;
  approved_letter_hash?: string | null;
  approved_at?: string | null;
  sources: VacancySource[];
};
type Tab = { id: string; label: string; statuses?: string[] };
type RetryResult = {
  recovered_stuck: number;
  matched_incomplete: number;
  requeued: number;
  scoring: {
    found: number;
    scored: number;
    hard_filtered: number;
    archived: number;
    errors: number;
    retryable_errors: number;
    skipped: number;
  };
};
type BulkArchiveResult = { requested: number; archived: number; skipped: number };

const TABS: Tab[] = [
  { id: "review", label: "к разбору", statuses: ["discovered", "scoring", "scored", "review", "score_error"] },
  { id: "selected", label: "выбраны", statuses: ["selected", "letter_draft", "approved", "queued_to_send"] },
  { id: "hold", label: "отложены", statuses: ["hold"] },
  { id: "rejected", label: "отклонены", statuses: ["rejected_by_user", "rejected_by_rule"] },
  { id: "archived", label: "архив", statuses: ["archived"] },
  { id: "all", label: "все" },
];

const STATUS_LABEL: Record<string, { label: string; tone: "neutral" | "ok" | "warn" | "err" | "yellow" | "coral" | "dark" }> = {
  discovered: { label: "найдена", tone: "neutral" },
  scoring: { label: "оценка", tone: "yellow" },
  scored: { label: "оценена", tone: "dark" },
  review: { label: "к разбору", tone: "dark" },
  selected: { label: "выбрана", tone: "ok" },
  letter_draft: { label: "письмо", tone: "ok" },
  approved: { label: "одобрена", tone: "ok" },
  queued_to_send: { label: "в очереди", tone: "yellow" },
  hold: { label: "отложена", tone: "warn" },
  rejected_by_user: { label: "отклонена вручную", tone: "coral" },
  rejected_by_rule: { label: "отклонена правилом", tone: "err" },
  archived: { label: "архив", tone: "neutral" },
  score_error: { label: "ошибка оценки", tone: "err" },
};

function salaryText(value: Record<string, unknown> | null): string | null {
  if (!value) return null;
  const from = value.from ?? value.min ?? value.lower;
  const to = value.to ?? value.max ?? value.upper;
  const currency = String(value.currency ?? value.currencyCode ?? "").trim();
  const gross = value.gross === true ? " gross" : "";
  const fmt = (v: unknown) => {
    const n = Number(v);
    return Number.isFinite(n) ? new Intl.NumberFormat("ru-RU").format(n) : null;
  };
  const left = fmt(from);
  const right = fmt(to);
  if (!left && !right) return null;
  if (left && right) return `${left}–${right} ${currency}${gross}`.trim();
  if (left) return `от ${left} ${currency}${gross}`.trim();
  return `до ${right} ${currency}${gross}`.trim();
}

function queryFor(tab: Tab, page: number) {
  const params = new URLSearchParams();
  for (const status of tab.statuses ?? []) params.append("status", status);
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(page * PAGE_SIZE));
  return `/api/vacancies?${params.toString()}`;
}

export default function VacanciesPage() {
  const [tabId, setTabId] = useState("review");
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<Vacancy[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [maintenanceBusy, setMaintenanceBusy] = useState(false);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const tab = useMemo(() => TABS.find((item) => item.id === tabId) ?? TABS[0], [tabId]);

  const load = useCallback(async () => {
    setRows(null);
    try {
      const data = await apiFetch<Vacancy[]>(queryFor(tab, page));
      setRows(data);
      setSelectedIds(new Set());
      setError(null);
    } catch (err) {
      setRows([]);
      setError(err instanceof Error ? err.message : "Не удалось загрузить вакансии");
    }
  }, [tab, page]);

  useEffect(() => { load(); }, [load]);

  function chooseTab(id: string) {
    setTabId(id);
    setPage(0);
    setOpenId(null);
    setSelectedIds(new Set());
  }

  function replaceRow(next: Vacancy) {
    setRows((current) => (current ?? []).map((row) => (row.id === next.id ? next : row)));
  }

  function removeIfLeavesTab(next: Vacancy) {
    if (tabId === "all") return;
    if (!(tab.statuses ?? []).includes(next.status)) {
      setRows((current) => (current ?? []).filter((row) => row.id !== next.id));
    }
  }

  async function decide(vacancy: Vacancy, action: "select" | "reject" | "hold" | "review" | "archive", reason?: string) {
    setBusyId(vacancy.id);
    setMessage(null);
    try {
      const next = await apiFetch<Vacancy>(`/api/vacancies/${vacancy.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ action, reason: reason || null }),
      });
      replaceRow(next);
      removeIfLeavesTab(next);
      setSelectedIds((current) => { const nextSet = new Set(current); nextSet.delete(vacancy.id); return nextSet; });
      if (action === "reject") { setRejectingId(null); setRejectReason(""); }
      if (action === "archive") setMessage("Вакансия убрана в архив без анализа причины.");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить статус");
    } finally {
      setBusyId(null);
    }
  }

  async function retryIncomplete() {
    setMaintenanceBusy(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiFetch<RetryResult>("/api/vacancies/maintenance/retry-incomplete", { method: "POST" });
      setMessage(
        `Повторная оценка: найдено ${result.matched_incomplete}, восстановлено зависших ${result.recovered_stuck}, ` +
        `оценено ${result.scoring.scored}, отклонено правилами ${result.scoring.hard_filtered}, ` +
        `ошибок ${result.scoring.errors + result.scoring.retryable_errors}, пропущено ${result.scoring.skipped}.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось повторить оценку");
    } finally {
      setMaintenanceBusy(false);
    }
  }

  async function bulkArchive() {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    setMaintenanceBusy(true);
    setMessage(null);
    setError(null);
    try {
      const result = await apiFetch<BulkArchiveResult>("/api/vacancies/bulk/archive", {
        method: "POST",
        body: JSON.stringify({ pipeline_ids: ids }),
      });
      setMessage(`Архивировано без анализа: ${result.archived}. Пропущено: ${result.skipped}.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось архивировать вакансии");
    } finally {
      setMaintenanceBusy(false);
    }
  }

  async function enrich(vacancy: Vacancy) {
    setBusyId(vacancy.id);
    try {
      const data = await apiFetch<{ vacancy: Vacancy }>(`/api/vacancies/${vacancy.id}/enrich`, { method: "POST" });
      replaceRow(data.vacancy);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось обновить вакансию из HH");
    } finally {
      setBusyId(null);
    }
  }

  function toggleSelected(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  return (
    <div className={styles.page}>
      <Card>
        <div className={styles.headerRow}>
          <div>
            <div className={styles.title}>Вакансии</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
              discovery → оценка → выбор → письмо → approval → очередь. Архив без причины не обучает правила.
            </div>
          </div>
          <div className={styles.spacer} />
          <Btn kind="yellow" size="sm" loading={maintenanceBusy} onClick={retryIncomplete}>повторить незавершённую оценку</Btn>
          {selectedIds.size > 0 && (
            <Btn kind="ghost" size="sm" disabled={maintenanceBusy} onClick={bulkArchive}>в архив ({selectedIds.size})</Btn>
          )}
          <Btn kind="ghost" size="sm" icon={<IRefresh size={14} />} onClick={load}>обновить</Btn>
        </div>
        <div className={styles.tabs} style={{ marginTop: 14 }}>
          {TABS.map((item) => (
            <button type="button" key={item.id} onClick={() => chooseTab(item.id)} className={`${styles.tab} ${item.id === tabId ? styles.tabActive : ""}`}>
              {item.label}
            </button>
          ))}
        </div>
      </Card>

      {message && <div style={{ padding: "10px 14px", borderRadius: 12, background: "var(--sage-soft)", fontSize: 12 }}>{message}</div>}
      {error && <div className={styles.error}>{error}</div>}

      {rows === null ? (
        <Card><Skeleton h={160} count={4} /></Card>
      ) : rows.length === 0 ? (
        <Card><EmptyState icon={<IList size={22} />} title="Здесь пока пусто" description="Новые вакансии появятся после discovery и оценки." /></Card>
      ) : (
        <div className={styles.list}>
          {rows.map((vacancy) => {
            const currentStatus = STATUS_LABEL[vacancy.status] ?? { label: vacancy.status, tone: "neutral" as const };
            const details = vacancy.score_details ?? {};
            const autoRejects = vacancy.auto_reject_details ?? details.auto_rejects ?? [];
            const open = openId === vacancy.id;
            const salary = salaryText(vacancy.salary);
            const busy = busyId === vacancy.id;
            const selectedLike = ["selected", "letter_draft", "approved", "queued_to_send"].includes(vacancy.status);
            const reviewableSelected = ["selected", "letter_draft"].includes(vacancy.status);
            const rejectedLike = ["rejected_by_user", "rejected_by_rule"].includes(vacancy.status);
            const finalLike = ["approved", "archived", "sending", "sent", "queued_to_send", "rejected_by_rule"].includes(vacancy.status);
            const canArchive = ARCHIVABLE.has(vacancy.status);

            return (
              <Card key={vacancy.id} className={styles.vacancyCard}>
                <div className={styles.cardHead}>
                  <div style={{ minWidth: 0, display: "flex", gap: 9, alignItems: "flex-start" }}>
                    {canArchive && (
                      <input type="checkbox" checked={selectedIds.has(vacancy.id)} onChange={() => toggleSelected(vacancy.id)} aria-label={`Выбрать ${vacancy.title} для архива`} />
                    )}
                    <div>
                      <div className={styles.role}>{vacancy.title || `vacancy ${vacancy.hh_vacancy_id}`}</div>
                      <div className={styles.company}>{[vacancy.employer_name, vacancy.area_name, salary].filter(Boolean).join(" · ")}</div>
                    </div>
                  </div>
                  <div className={`${styles.score} ${vacancy.score == null ? styles.scoreMuted : ""}`}>{vacancy.score == null ? "—" : vacancy.score}</div>
                </div>

                <div className={styles.meta}>
                  <Tag tone={currentStatus.tone} dot>{currentStatus.label}</Tag>
                  {vacancy.hard_filter_reason && <Tag tone="err">hard filter</Tag>}
                  {typeof details.confidence === "number" && <Tag tone="neutral">confidence {details.confidence}%</Tag>}
                  {vacancy.sources.map((source) => <Tag key={source.id} tone="neutral">{source.name}</Tag>)}
                </div>

                {vacancy.score_explanation && <div className={styles.summary}>{vacancy.score_explanation}</div>}

                {!finalLike && !rejectedLike && (
                  <div className={styles.actions}>
                    {!selectedLike && <Btn kind="primary" size="sm" loading={busy} onClick={() => decide(vacancy, "select")}>выбрать</Btn>}
                    {reviewableSelected ? (
                      <Btn kind="ghost" size="sm" disabled={busy} onClick={() => decide(vacancy, "review")}>вернуть</Btn>
                    ) : !selectedLike ? (
                      <>
                        <Btn kind="soft" size="sm" disabled={busy} onClick={() => decide(vacancy, "hold", "отложено пользователем")}>отложить</Btn>
                        <Btn kind="coral" size="sm" disabled={busy} onClick={() => { setRejectingId(vacancy.id); setRejectReason(vacancy.user_decision_reason ?? ""); }}>отклонить с причиной</Btn>
                        {canArchive && <Btn kind="ghost" size="sm" disabled={busy} onClick={() => decide(vacancy, "archive")}>в архив без анализа</Btn>}
                      </>
                    ) : null}
                  </div>
                )}

                {selectedLike && (
                  <CoverLetterEditor
                    vacancyId={vacancy.id}
                    status={vacancy.status}
                    initialDraft={vacancy.cover_letter_draft}
                    meta={vacancy.cover_letter_meta ?? {}}
                    onUpdated={(next) => setRows((current) => (current ?? []).map((row) => row.id === vacancy.id ? { ...row, status: next.status, cover_letter_draft: next.cover_letter_draft, cover_letter_meta: next.cover_letter_meta, approved_letter_hash: next.approved_letter_hash, approved_at: next.approved_at } : row))}
                  />
                )}

                {rejectingId === vacancy.id && (
                  <div className={styles.rejectBox}>
                    <textarea value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="Почему вакансия не подходит? Эта причина может стать предложением нового правила." />
                    <div className={styles.rejectActions}>
                      <Btn kind="coral" size="sm" loading={busy} disabled={!rejectReason.trim()} onClick={() => decide(vacancy, "reject", rejectReason.trim())}>подтвердить</Btn>
                      <Btn kind="ghost" size="sm" disabled={busy} onClick={() => setRejectingId(null)}>отмена</Btn>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 7 }}>Если объяснять причину не нужно, используй «в архив без анализа».</div>
                  </div>
                )}

                <button type="button" className={styles.detailsButton} onClick={() => setOpenId(open ? null : vacancy.id)} aria-expanded={open}>
                  {open ? "скрыть детали" : "показать детали"}
                </button>

                {open && (
                  <div className={styles.details}>
                    {autoRejects.length > 0 && (
                      <div className={styles.detailBlock}>
                        <div className={styles.detailTitle}>почему отклонена автоматически</div>
                        <div style={{ display: "grid", gap: 10 }}>
                          {autoRejects.map((item, index) => (
                            <div key={`${item.rule_id ?? item.reason ?? "system"}-${index}`}>
                              <div style={{ fontSize: 13, fontWeight: 700 }}>
                                {item.type === "rule" ? `Правило${item.version ? ` v${item.version}` : ""}: ${item.name ?? "без названия"}` : `Системный фильтр: ${item.name ?? item.reason ?? "hard reject"}`}
                              </div>
                              {item.instruction && <div style={{ fontSize: 12, marginTop: 3 }}>{item.instruction}</div>}
                              {(item.matches ?? []).length > 0 && (
                                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                                  {(item.matches ?? []).map((match) => <Tag key={`${match.field}:${match.term}`} tone="neutral">{match.field}: {match.term}</Tag>)}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className={styles.detailGrid}>
                      <div className={styles.detailBlock}><div className={styles.detailTitle}>плюсы</div><ul className={styles.detailList}>{(details.pros?.length ? details.pros : ["нет данных"]).map((item) => <li key={item}>{item}</li>)}</ul></div>
                      <div className={styles.detailBlock}><div className={styles.detailTitle}>риски</div><ul className={styles.detailList}>{(details.risks?.length ? details.risks : [vacancy.hard_filter_reason || "нет данных"]).map((item) => <li key={item}>{item}</li>)}</ul></div>
                      <div className={styles.detailBlock}><div className={styles.detailTitle}>неизвестно</div><ul className={styles.detailList}>{(details.unknowns?.length ? details.unknowns : ["нет данных"]).map((item) => <li key={item}>{item}</li>)}</ul></div>
                    </div>

                    {vacancy.user_decision_reason && <div className={styles.detailBlock}><div className={styles.detailTitle}>решение пользователя</div><div style={{ fontSize: 13 }}>{vacancy.user_decision_reason}</div></div>}

                    <div>
                      <div className={styles.detailTitle}>описание вакансии</div>
                      {vacancy.description ? <div className={styles.description}>{vacancy.description}</div> : <div style={{ fontSize: 13, color: "var(--muted)" }}>Полный текст ещё не загружен.</div>}
                    </div>

                    <div className={styles.actions}>
                      {vacancy.vacancy_url && <a href={vacancy.vacancy_url} target="_blank" rel="noopener noreferrer" className="oc-btn oc-btn--ghost oc-btn--sm"><IExternal size={14} />открыть HH</a>}
                      {!finalLike && <Btn kind="ghost" size="sm" loading={busy} onClick={() => enrich(vacancy)}>обновить из HH</Btn>}
                    </div>
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className={styles.pager}>
          <Btn kind="ghost" size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>назад</Btn>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>страница {page + 1}</span>
          <Btn kind="ghost" size="sm" disabled={rows.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>дальше</Btn>
        </div>
      )}
    </div>
  );
}
