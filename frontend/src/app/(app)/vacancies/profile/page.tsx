"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Card, EmptyState, Skeleton, Tag } from "@/components/otclick/ui";
import { IList } from "@/components/otclick/icons";

type TargetRole = {
  role: string;
  priority: number;
  condition?: string;
};

type Fact = {
  fact_key: string;
  category: string;
  title: string;
  statement: string;
  metrics: Record<string, unknown>;
  tags: string[];
  source_name?: string | null;
};

type Profile = {
  target_roles?: TargetRole[];
  next_role_priorities?: string[];
  not_interested?: string[];
  organization_level?: {
    preferred?: string[];
    acceptable?: string;
  };
  industries?: {
    priority?: string[];
    not_interesting_as_standalone_core?: string[];
    diversified_holding_exception?: boolean;
  };
  business_scale?: {
    standalone_cio_cdto_revenue_rub_billion?: { from?: number; to?: number };
    companies_above_rub_billion?: number;
    above_100_condition?: string;
  };
  compensation?: {
    target_fixed_net_rub_per_month?: number;
    target_bonus?: string;
    flexibility?: string[];
  };
  positioning?: {
    working_hypothesis?: string;
    target_image?: string[];
    not_positioning?: string[];
  };
  strong_role_signals?: string[];
  weak_role_signals?: string[];
  achievement_format?: string;
  resume_first_screen_should_show?: string[];
  claim_guardrails?: string[];
};

type CandidateContext = {
  version: number;
  source_name: string;
  profile: Profile;
  facts: Fact[];
};

function Rubles({ value }: { value?: number }) {
  if (!value) return <span>—</span>;
  return <span>{new Intl.NumberFormat("ru-RU").format(value)} ₽ net / мес.</span>;
}

function ListBlock({ title, items }: { title: string; items?: string[] }) {
  const safe = items ?? [];
  return (
    <div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{title}</div>
      {safe.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--muted)" }}>—</div>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 5, fontSize: 13, lineHeight: 1.45 }}>
          {safe.map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
    </div>
  );
}

function metricText(metrics: Record<string, unknown>) {
  return Object.entries(metrics)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`);
}

export default function CandidateProfilePage() {
  const [data, setData] = useState<CandidateContext | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<CandidateContext>("/api/candidate-context")
      .then((next) => {
        setData(next);
        setError(null);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Не удалось загрузить профиль кандидата");
        setData(null);
      });
  }, []);

  const groupedFacts = useMemo(() => {
    const groups = new Map<string, Fact[]>();
    for (const fact of data?.facts ?? []) {
      const key = fact.category || "other";
      groups.set(key, [...(groups.get(key) ?? []), fact]);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b, "ru"));
  }, [data]);

  if (!data && !error) {
    return <Card><Skeleton h={110} count={5} /></Card>;
  }

  if (!data) {
    return (
      <Card>
        <EmptyState
          icon={<IList size={22} />}
          title="Профиль не загружен"
          description={error ?? "Candidate context отсутствует."}
        />
      </Card>
    );
  }

  const profile = data.profile ?? {};
  const scale = profile.business_scale?.standalone_cio_cdto_revenue_rub_billion;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 20, fontWeight: 760 }}>Профиль кандидата</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3, wordBreak: "break-word" }}>
              {data.source_name}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <Tag tone="neutral">v{data.version}</Tag>
          <Tag tone="dark">{data.facts.length} facts</Tag>
        </div>
        <div style={{ marginTop: 14, padding: 12, borderRadius: 14, background: "var(--bg-deep)", fontSize: 14, lineHeight: 1.5 }}>
          {profile.positioning?.working_hypothesis ?? "Позиционирование не задано."}
        </div>
      </Card>

      <Card>
        <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Целевые роли</div>
        <div style={{ display: "grid", gap: 8 }}>
          {(profile.target_roles ?? []).map((role) => (
            <div key={`${role.priority}:${role.role}`} style={{ padding: 10, borderRadius: 12, background: "var(--bg-deep)" }}>
              <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                <Tag tone={role.priority === 1 ? "ok" : "neutral"}>#{role.priority}</Tag>
                <div style={{ fontSize: 14, fontWeight: 720 }}>{role.role}</div>
              </div>
              {role.condition && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6, lineHeight: 1.45 }}>{role.condition}</div>}
            </div>
          ))}
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))", gap: 14 }}>
        <Card>
          <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Масштаб и уровень</div>
          <div style={{ display: "grid", gap: 10, fontSize: 13 }}>
            <div>
              <div style={{ color: "var(--muted)", fontSize: 11 }}>standalone CIO/CDTO</div>
              <div style={{ marginTop: 2, fontWeight: 650 }}>
                {scale?.from ?? "—"}–{scale?.to ?? "—"} млрд ₽ выручки
              </div>
            </div>
            <ListBlock title="предпочтительный уровень" items={profile.organization_level?.preferred} />
            {profile.organization_level?.acceptable && (
              <div>
                <div style={{ color: "var(--muted)", fontSize: 11 }}>допустимо</div>
                <div style={{ marginTop: 3, lineHeight: 1.45 }}>{profile.organization_level.acceptable}</div>
              </div>
            )}
            {profile.business_scale?.above_100_condition && (
              <div style={{ padding: 9, borderRadius: 10, background: "var(--surface)", lineHeight: 1.45 }}>
                &gt;{profile.business_scale.companies_above_rub_billion ?? 100} млрд ₽: {profile.business_scale.above_100_condition}
              </div>
            )}
          </div>
        </Card>

        <Card>
          <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Компенсация</div>
          <div style={{ fontSize: 18, fontWeight: 760 }}>
            <Rubles value={profile.compensation?.target_fixed_net_rub_per_month} />
          </div>
          {profile.compensation?.target_bonus && (
            <div style={{ fontSize: 13, lineHeight: 1.45, marginTop: 8 }}>{profile.compensation.target_bonus}</div>
          )}
          <div style={{ marginTop: 10 }}>
            <ListBlock title="гибкость" items={profile.compensation?.flexibility} />
          </div>
        </Card>
      </div>

      <Card>
        <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Отрасли</div>
        <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>приоритет</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(profile.industries?.priority ?? []).map((item) => <Tag key={item} tone="ok">{item}</Tag>)}
        </div>
        <div style={{ fontSize: 11, color: "var(--muted)", margin: "12px 0 6px" }}>неинтересно как самостоятельное ядро</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(profile.industries?.not_interesting_as_standalone_core ?? []).map((item) => <Tag key={item} tone="coral">{item}</Tag>)}
        </div>
        {profile.industries?.diversified_holding_exception && (
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 10 }}>
            Исключение: эти направления допустимы внутри диверсифицированного холдинга.
          </div>
        )}
      </Card>

      <Card>
        <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 12 }}>Что должна дать следующая роль</div>
        <ListBlock title="приоритеты" items={profile.next_role_priorities} />
        <div style={{ marginTop: 14 }}>
          <ListBlock title="не интересно" items={profile.not_interested} />
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))", gap: 14 }}>
        <Card>
          <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Сильные сигналы вакансии</div>
          <ListBlock title="" items={profile.strong_role_signals} />
        </Card>
        <Card>
          <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Слабые сигналы вакансии</div>
          <ListBlock title="" items={profile.weak_role_signals} />
        </Card>
      </div>

      <Card>
        <div style={{ fontSize: 15, fontWeight: 750, marginBottom: 10 }}>Claim guardrails</div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>
          Эти ограничения передаются scorer/writer. Неподтверждённые утверждения нельзя использовать как достижения.
        </div>
        <ListBlock title="" items={profile.claim_guardrails} />
      </Card>

      <Card>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
          <div style={{ fontSize: 15, fontWeight: 750 }}>Подтверждённые факты</div>
          <Tag tone="dark">{data.facts.length}</Tag>
        </div>
        {groupedFacts.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--muted)" }}>Нет активных facts.</div>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {groupedFacts.map(([category, facts]) => (
              <details key={category} open>
                <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 720, marginBottom: 7 }}>
                  {category} · {facts.length}
                </summary>
                <div style={{ display: "grid", gap: 8 }}>
                  {facts.map((fact) => (
                    <div key={fact.fact_key} style={{ padding: 11, borderRadius: 12, background: "var(--bg-deep)" }}>
                      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                        <div style={{ fontSize: 13, fontWeight: 700 }}>{fact.title}</div>
                        <Tag tone="neutral">{fact.fact_key}</Tag>
                      </div>
                      <div style={{ fontSize: 13, lineHeight: 1.48, marginTop: 6 }}>{fact.statement}</div>
                      {metricText(fact.metrics).length > 0 && (
                        <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 7 }}>
                          {metricText(fact.metrics).map((metric) => <Tag key={metric} tone="neutral">{metric}</Tag>)}
                        </div>
                      )}
                      {fact.tags.length > 0 && (
                        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 7 }}>
                          {fact.tags.join(" · ")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
