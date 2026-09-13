"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, EmptyState, Skeleton, Tag } from "@/components/otclick/ui";
import { IExternal, IList, IRefresh } from "@/components/otclick/icons";
import CoverLetterEditor from "./cover-letter-editor";
import styles from "./page.module.css";

const PAGE_SIZE = 25;

type VacancySource = {
  id: string;
  name: string;
  source_type: string;
};

type ScoreDetails = {
  components?: Record<string, number>;
  pros?: string[];
  risks?: string[];
  unknowns?: string[];
  confidence?: number;
  hard_filter?: boolean;
  error?: string;
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
  user_decision_reason: string | null;
  cover_letter_draft: string | null;
  cover_letter_meta: Record<string, unknown>;
  approved_letter_hash?: string | null;
  approved_at?: string | null;
  sources: VacancySource[];
};

type Tab = {
  id: string;
  label: string;
  statuses?: string[];
};

const TABS: Tab[] = [
  { id: "review", label: "к разбору", statuses: ["discovered", "scoring", "scored", "review", "score_error"] },
  { id: "selected", label: "выбраны", statuses: ["selected", "letter_draft", "approved", "queued_to_send"] },
  { id: "hold", label: "отложены", statuses: ["hold"] },
  { id: "rejected", label: "отклонены", statuses: ["rejected_by_user"] },
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
  rejected_by_user: { label: "отклонена", tone: "coral" },
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
  const [openId, setOpenId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const tab = useMemo(() => TABS.find((item) => item.id === tabId) ?? TABS[0], [tabId]);

  const load = useCallback(async () => {
    setRows(null);
    try {
      const data = await apiFetch<Vacancy[]>(queryFor(tab, page));
      setRows(data);
      setError(null);
    } catch (err) {
      setRows([]);
      setError(err instanceof Error ? err.message : "Не удалось загрузить вакансии");
    }
  }, [tab, page]);

  useEffect(() => {
    load();
  }, [load]);

  function chooseTab(id: string) {
    setTabId(id);
    setPage(0);
    setOpenId(null);
  }

  function replaceRow(next: Vacancy) {
    setRows((current) => (current ?? []).map((row) => (row.id === next.id ? next : row)));
  }

  async function decide(vacancy: Vacancy, action: "select" | "reject" | "hold" | "review", reason?: string) {
    setBusyId(vacancy.id);
    try {
      const next = await apiFetch<Vacancy>(`/api/vacancies/${vacancy.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ action, reason: reason || null }),
      });
      replaceRow(next);
      if (action === "reject") {
        setRejectingId(null);
        setRejectReason("");
      }
      if (tabId !== "all") {
        const stays = (tab.statuses ?? []).includes(next.status);
        if (!stays) setRows((current) => (current ?? []).filter((row) => row.id !== vacancy.id));
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить статус");
    } finally {
      setBusyId(null);
    }
  }

  async function enrich(vacancy: Vacancy) {
    setBusyId(vacancy.id);
    try {
      const data = await apiFetch<{ vacancy: Vacancy }>(`/api/vacancies/${vacancy.id}/enrich`, {
        method: "POST",
      });
      replaceRow(data.vacancy);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось обновить вакансию из HH");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className={styles.page}>
      <Card>
        <div className={styles.headerRow}>
          <div>
            <div className={styles.title}>Вакансии</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
              discovery → оценка → выбор → письмо → approval → очередь. Реальная отправка отключена.
            </div>
          </div>
          <div className={styles.spacer} />
          <Btn kind="ghost" size="sm" icon={<IRefresh size={14} />} onClick={load}>
            обновить
          </Btn>
        </div>
        <div className={styles.tabs} style={{ marginTop: 14 }}>
          {TABS.map((item) => (
            <button
              type="button"
              key={item.id}
              onClick={() => chooseTab(item.id)}
              className={`${styles.tab} ${item.id === tabId ? styles.tabActive : ""}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </Card>

      {error && <div className={styles.error}>{error}</div>}

      {rows === null ? (
        <Card><Skeleton h={160} count={4} /></Card>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IList size={22} />}
            title="Здесь пока пусто"
            description="Новые вакансии появятся после discovery и оценки."
          />
        </Card>
      ) : (
        <div className={styles.list}>
          {rows.map((vacancy) => {
            const currentStatus = STATUS_LABEL[vacancy.status] ?? { label: vacancy.status, tone: "neutral" as const };
            const details = vacancy.score_details ?? {};
            const open = openId === vacancy.id;
            const salary = salaryText(vacancy.salary);
            const busy = busyId === vacancy.id;
            const selectedLike = ["selected", "letter_draft", "approved", "queued_to_send"].includes(vacancy.status);
            const reviewableSelected = ["selected", "letter_draft"].includes(vacancy.status);
            const finalLike = ["approved", "archived", "sending", "sent", "queued_to_send"].includes(vacancy.status);

            return (
              <Card key={vacancy.id} className={styles.vacancyCard}>
                <div className={styles.cardHead}>
                  <div style={{ minWidth: 0 }}>
                    <div className={styles.role}>{vacancy.title || `vacancy ${vacancy.hh_vacancy_id}`}</div>
                    <div className={styles.company}>
                      {[vacancy.employer_name, vacancy.area_name, salary].filter(Boolean).join(" · ")}
                    </div>
                  </div>
                  <div className={`${styles.score} ${vacancy.score == null ? styles.scoreMuted : ""}`}>
                    {vacancy.score == null ? "—" : vacancy.score}
                  </div>
                </div>

                <div className={styles.meta}>
                  <Tag tone={currentStatus.tone} dot>{currentStatus.label}</Tag>
                  {vacancy.hard_filter_reason && <Tag tone="err">hard filter</Tag>}
                  {typeof details.confidence === "number" && (
                    <Tag tone="neutral">confidence {details.confidence}%</Tag>
                  )}
                  {vacancy.sources.map((source) => (
                    <Tag key={source.id} tone="neutral">{source.name}</Tag>
                  ))}
                </div>

                {vacancy.score_explanation && (
                  <div className={styles.summary}>{vacancy.score_explanation}</div>
                )}

                {!finalLike && (
                  <div className={styles.actions}>
                    {!selectedLike && (
                      <Btn kind="primary" size="sm" loading={busy} onClick={() => decide(vacancy, "select")}>
                        выбрать
                      </Btn>
                    )}
                    {reviewableSelected ? (
                      <Btn kind="ghost" size="sm" disabled={busy} onClick={() => decide(vacancy, "review")}>
                        вернуть
                      </Btn>
                    ) : !selectedLike ? (
                      <>
                        <Btn kind="soft" size="sm" disabled={busy} onClick={() => decide(vacancy, "hold", "отложено пользователем")}>
                          отложить
                        </Btn>
                        <Btn
                          kind="coral"
                          size="sm"
                          disabled={busy}
                          onClick={() => {
                            setRejectingId(vacancy.id);
                            setRejectReason(vacancy.user_decision_reason ?? "");
                          }}
                        >
                          отклонить
                        </Btn>
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
                    onUpdated={(next) => {
                      setRows((current) =>
                        (current ?? []).map((row) =>
                          row.id === vacancy.id
                            ? {
                                ...row,
                                status: next.status,
                                cover_letter_draft: next.cover_letter_draft,
                                cover_letter_meta: next.cover_letter_meta,
                                approved_letter_hash: next.approved_letter_hash,
                                approved_at: next.approved_at,
                              }
                            : row,
                        ),
                      );
                    }}
                  />
                )}

                {rejectingId === vacancy.id && (
                  <div className={styles.rejectBox}>
                    <textarea
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder="Почему вакансия не подходит? Это потом используется для предложения правил."
                    />
                    <div className={styles.rejectActions}>
                      <Btn
                        kind="coral"
                        size="sm"
                        loading={busy}
                        disabled={!rejectReason.trim()}
                        onClick={() => decide(vacancy, "reject", rejectReason.trim())}
                      >
                        подтвердить
                      </Btn>
                      <Btn kind="ghost" size="sm" disabled={busy} onClick={() => setRejectingId(null)}>
                        отмена
                      </Btn>
                    </div>
                  </div>
                )}

                <button
                  type="button"
                  className={styles.detailsButton}
                  onClick={() => setOpenId(open ? null : vacancy.id)}
                  aria-expanded={open}
                >
                  {open ? "скрыть детали" : "показать детали"}
                </button>

                {open && (
                  <div className={styles.details}>
                    <div className={styles.detailGrid}>
                      <div className={styles.detailBlock}>
                        <div className={styles.detailTitle}>плюсы</div>
                        <ul className={styles.detailList}>
                          {(details.pros?.length ? details.pros : ["нет данных"]).map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </div>
                      <div className={styles.detailBlock}>
                        <div className={styles.detailTitle}>риски</div>
                        <ul className={styles.detailList}>
                          {(details.risks?.length ? details.risks : [vacancy.hard_filter_reason || "нет данных"]).map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </div>
                      <div className={styles.detailBlock}>
                        <div className={styles.detailTitle}>неизвестно</div>
                        <ul className={styles.detailList}>
                          {(details.unknowns?.length ? details.unknowns : ["нет данных"]).map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </div>
                    </div>

                    {vacancy.user_decision_reason && (
                      <div className={styles.detailBlock}>
                        <div className={styles.detailTitle}>решение пользователя</div>
                        <div style={{ fontSize: 13 }}>{vacancy.user_decision_reason}</div>
                      </div>
                    )}

                    <div>
                      <div className={styles.detailTitle}>описание вакансии</div>
                      {vacancy.description ? (
                        <div className={styles.description}>{vacancy.description}</div>
                      ) : (
                        <div style={{ fontSize: 13, color: "var(--muted)" }}>Полный текст ещё не загружен.</div>
                      )}
                    </div>

                    <div className={styles.actions}>
                      {vacancy.vacancy_url && (
                        <a
                          href={vacancy.vacancy_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="oc-btn oc-btn--ghost oc-btn--sm"
                        >
                          <IExternal size={14} />
                          открыть HH
                        </a>
                      )}
                      {!finalLike && (
                        <Btn kind="ghost" size="sm" loading={busy} onClick={() => enrich(vacancy)}>
                          обновить из HH
                        </Btn>
                      )}
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
          <Btn kind="ghost" size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
            назад
          </Btn>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>страница {page + 1}</span>
          <Btn kind="ghost" size="sm" disabled={rows.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>
            дальше
          </Btn>
        </div>
      )}
    </div>
  );
}
