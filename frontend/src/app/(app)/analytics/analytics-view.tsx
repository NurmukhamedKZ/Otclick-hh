"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Analytics, AnalyticsBreakdown, RelevanceVerdict } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/status";
import { Card, EmptyState, SegmentedTabs, Skeleton, Tag } from "@/components/otclick/ui";
import { IChart } from "@/components/otclick/icons";

const PERIODS = [
  { id: "7", label: "7 дней" },
  { id: "30", label: "30 дней" },
  { id: "90", label: "90 дней" },
];

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 1000) / 10}%`;
}

function hours(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v < 24) return `${v} ч`;
  return `${Math.round((v / 24) * 10) / 10} дн`;
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <Card tone="light" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div style={{ fontSize: 15, fontWeight: 700 }}>{title}</div>
        {hint && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>{hint}</div>}
      </div>
      {children}
    </Card>
  );
}

function Kpi({
  label,
  value,
  hint,
  hero,
}: {
  label: string;
  value: string;
  hint?: string;
  hero?: boolean;
}) {
  return (
    <Card tone={hero ? "dark" : "light"} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 12, color: hero ? "rgba(245,241,230,.7)" : "var(--muted)" }}>{label}</div>
      <div style={{ fontSize: hero ? 34 : 26, fontWeight: 800, lineHeight: 1.1 }}>{value}</div>
      {hint && (
        <div style={{ fontSize: 12, color: hero ? "rgba(245,241,230,.7)" : "var(--muted)" }}>{hint}</div>
      )}
    </Card>
  );
}

const FUNNEL_COLORS = ["var(--ink)", "var(--ink)", "var(--yellow)", "var(--coral)"];

function Funnel({ data }: { data: Analytics["funnel"] }) {
  const steps = [
    { label: "Отклик отправлен", value: data.sent },
    { label: "Просмотрен работодателем", value: data.viewed },
    { label: "Ответ получен", value: data.replied },
    { label: "Приглашение", value: data.invited },
  ];
  const max = Math.max(...steps.map((s) => s.value), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {steps.map((s, i) => {
        const prev = i === 0 ? null : steps[i - 1].value;
        const conv = prev && prev > 0 ? s.value / prev : null;
        return (
          <div key={s.label}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
              <span>{s.label}</span>
              <span style={{ fontWeight: 700 }}>
                {s.value}
                {conv !== null && (
                  <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 8 }}>
                    {pct(conv)} от предыдущего
                  </span>
                )}
              </span>
            </div>
            <div style={{ height: 10, borderRadius: 999, background: "var(--bg-deep)", overflow: "hidden" }}>
              <div
                style={{
                  width: `${(s.value / max) * 100}%`,
                  height: "100%",
                  borderRadius: 999,
                  background: FUNNEL_COLORS[i],
                  transition: "width var(--dur) var(--ease)",
                }}
              />
            </div>
          </div>
        );
      })}
      <div style={{ display: "flex", gap: 14, fontSize: 12, color: "var(--muted)", flexWrap: "wrap" }}>
        <span>ждём ответа: {data.waiting}</span>
        <span>отказов: {data.discarded}</span>
      </div>
    </div>
  );
}

function DailyChart({ rows }: { rows: Analytics["daily"] }) {
  if (rows.length === 0) {
    return <div style={{ fontSize: 13, color: "var(--muted)" }}>нет откликов за период</div>;
  }
  const max = Math.max(...rows.map((r) => r.sent), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 90 }} role="img" aria-label="отклики по дням">
      {rows.map((r) => (
        <div
          key={r.date}
          title={`${r.date}: ${r.sent} откликов, ${r.invited} приглашений`}
          style={{ flex: 1, minWidth: 3, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 1 }}
        >
          {r.invited > 0 && (
            <div style={{ height: `${(r.invited / max) * 80}px`, background: "var(--coral)", borderRadius: "3px 3px 0 0" }} />
          )}
          <div style={{ height: `${(r.sent / max) * 80}px`, background: "var(--bg-deep)", borderRadius: r.invited > 0 ? 0 : "3px 3px 0 0" }} />
        </div>
      ))}
    </div>
  );
}

function BreakdownTable({
  rows,
  labelOf,
  head,
}: {
  rows: AnalyticsBreakdown[];
  labelOf: (r: AnalyticsBreakdown) => string;
  head: string;
}) {
  if (rows.length === 0) {
    return <div style={{ fontSize: 13, color: "var(--muted)" }}>нет данных за период</div>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ color: "var(--muted)", textAlign: "right" }}>
            <th style={{ textAlign: "left", fontWeight: 500, padding: "4px 0" }}>{head}</th>
            <th style={{ fontWeight: 500 }}>откликов</th>
            <th style={{ fontWeight: 500 }}>ответов</th>
            <th style={{ fontWeight: 500 }}>приглашений</th>
            <th style={{ fontWeight: 500 }}>конв. на собес</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ borderTop: "1px solid var(--bg-deep)", textAlign: "right" }}>
              <td style={{ textAlign: "left", padding: "7px 8px 7px 0", maxWidth: 260 }}>{labelOf(r)}</td>
              <td>{r.sent}</td>
              <td>{r.replied}</td>
              <td>{r.invited}</td>
              <td style={{ fontWeight: 700 }}>{pct(r.invite_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const VERDICT_TABS = [
  { id: "false", label: "Отсеяно" },
  { id: "true", label: "Оставлено" },
];

function RelevanceLog() {
  const [relevant, setRelevant] = useState("false");
  const { data, isPending } = useQuery({
    queryKey: ["relevance-log", relevant],
    queryFn: () =>
      apiFetch<RelevanceVerdict[]>(`/api/analytics/relevance?relevant=${relevant}&limit=100`),
    staleTime: 60_000,
  });

  return (
    <Section title="Решения AI-фильтра" hint="какие вакансии ИИ оставил, а какие убрал — и почему">
      <SegmentedTabs items={VERDICT_TABS} value={relevant} onChange={setRelevant} label="Вердикт" />
      {isPending ? (
        <Skeleton h={40} count={3} />
      ) : !data || data.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          пусто — AI-фильтр ещё не выносил таких решений
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 420, overflowY: "auto" }}>
          {data.map((v) => (
            <div key={v.vacancy_id} style={{ fontSize: 13, borderTop: "1px solid var(--bg-deep)", paddingTop: 8 }}>
              <a
                href={`https://hh.ru/vacancy/${v.vacancy_id}`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "var(--ink)", fontWeight: 600 }}
              >
                {v.vacancy_name}
              </a>
              {v.reason && (
                <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{v.reason}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

export default function AnalyticsView() {
  const [days, setDays] = useState("30");
  const { data, isPending, error } = useQuery({
    queryKey: ["analytics", days],
    queryFn: () => apiFetch<Analytics>(`/api/analytics?days=${days}`),
    staleTime: 60_000,
  });

  if (isPending) {
    return <Skeleton h={120} count={4} />;
  }
  if (error || !data || data.error) {
    return (
      <Card tone="light">
        <EmptyState
          icon={<IChart />}
          title="Аналитика недоступна"
          description={
            (error as Error)?.message ??
            "Не удалось посчитать метрики. Нули на графиках были бы неправдой — попробуйте позже."
          }
        />
      </Card>
    );
  }
  if (data.funnel.sent === 0) {
    return (
      <>
        <SegmentedTabs items={PERIODS} value={days} onChange={setDays} label="Период" />
        <Card tone="light" style={{ marginTop: 16 }}>
          <EmptyState
            icon={<IChart />}
            title="Пока нет отправленных откликов"
            description="Запустите автоотклик — метрики появятся, как только уйдут первые отклики."
            action={{ label: "На главную", href: "/dashboard" }}
          />
        </Card>
        <div style={{ marginTop: 18 }}>
          <RelevanceLog />
        </div>
      </>
    );
  }

  const stuck = data.kpi.stuck_forms + data.kpi.stuck_captcha + data.kpi.stuck_drafts;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <SegmentedTabs items={PERIODS} value={days} onChange={setDays} label="Период" />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))", gap: 14 }}>
        <Kpi
          hero
          label="Конверсия на собеседование"
          value={pct(data.kpi.invite_rate)}
          hint={`${data.funnel.invited} приглашений из ${data.funnel.sent} откликов`}
        />
        <Kpi label="Ответ работодателя" value={pct(data.kpi.reply_rate)} hint={`${data.funnel.replied} ответов`} />
        <Kpi
          label="Медиана до реакции"
          value={hours(data.kpi.median_reaction_hours)}
          hint="от отклика до приглашения/отказа"
        />
        <Kpi
          label="Ждёт вас"
          value={String(stuck)}
          hint={`формы ${data.kpi.stuck_forms} · капчи ${data.kpi.stuck_captcha} · черновики ${data.kpi.stuck_drafts}`}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 18 }}>
        <Section title="Воронка" hint="каждая ступень — процент от предыдущей">
          <Funnel data={data.funnel} />
        </Section>
        <Section title="Отклики по дням" hint="серое — отправлено, коралловое — приглашения">
          <DailyChart rows={data.daily} />
        </Section>
      </div>

      <Section title="По фильтрам" hint="какой поиск приносит собеседования, а какой жжёт лимит">
        <BreakdownTable rows={data.by_filter} head="Фильтр" labelOf={(r) => r.name || "без фильтра"} />
      </Section>

      <Section title="По резюме" hint="какое резюме работает лучше">
        <BreakdownTable rows={data.by_resume} head="Резюме" labelOf={(r) => r.title || "без резюме"} />
      </Section>

      <Section title="Сопроводительное письмо" hint="стоит ли AI-письмо своих денег">
        <BreakdownTable
          rows={data.by_letter}
          head="Письмо"
          labelOf={(r) => (r.with_letter ? "с письмом" : "без письма")}
        />
      </Section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 18 }}>
        <Section title="AI-фильтр вакансий" hint="сколько мусора отсеяно до отклика">
          <div style={{ display: "flex", gap: 22, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 24, fontWeight: 800 }}>{data.ai_filter.checked}</div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>проверено</div>
            </div>
            <div>
              <div style={{ fontSize: 24, fontWeight: 800 }}>{data.ai_filter.dropped}</div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>отсеяно</div>
            </div>
            <div>
              <div style={{ fontSize: 24, fontWeight: 800 }}>{pct(data.ai_filter.drop_rate)}</div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>доля отсева</div>
            </div>
          </div>
        </Section>

        <Section title="Почему отклик не ушёл" hint="попытки, не дошедшие до hh">
          {data.failures.length === 0 ? (
            <div style={{ fontSize: 13, color: "var(--muted)" }}>всё ушло без ошибок</div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {data.failures.map((f) => (
                <Tag key={f.status} tone="neutral">
                  {STATUS_LABEL[f.status] ?? f.status}: {f.count}
                </Tag>
              ))}
            </div>
          )}
        </Section>
      </div>

      <RelevanceLog />

      <Section title="Молчащие работодатели" hint="3+ отклика без единого ответа — кандидаты в чёрный список">
        {data.silent_employers.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--muted)" }}>таких нет</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {data.silent_employers.map((e) => (
              <div key={e.employer_id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <a
                  href={`https://hh.ru/employer/${e.employer_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "var(--ink)" }}
                >
                  {e.employer_name || `Работодатель ${e.employer_id}`}
                </a>
                <span style={{ color: "var(--muted)" }}>{e.sent} откликов без ответа</span>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
