"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, PageHeader, Tag } from "@/components/otclick/ui";
import { IBolt, ICheck } from "@/components/otclick/icons";
import type { BillingStatus, PortalResponse, SubscribeResponse } from "@/lib/types";
import { pushToast } from "@/components/toaster";

function fmtDate(s: string | null): string {
  return s ? new Date(s).toLocaleDateString("ru-RU") : "—";
}

type Plan = {
  id: string;
  name: string;
  price: string;
  period: string;
  sub: string;
  popular?: boolean;
  feats: string[];
};

// Mirrors the landing pricing (app/page.tsx PLANS). Free tier is the no-card
// onboarding magnet, not a billable plan — surfaced here only as current status.
const PLANS: Plan[] = [
  {
    id: "sprint",
    name: "Спринт",
    price: "1 000 ₸",
    period: "7 дней",
    sub: "Закрыть поиск за один спринт. Низкий коммит.",
    feats: [
      "До 100 откликов в день",
      "AI-сопроводительные под каждую вакансию",
      "Агент отвечает рекрутёрам и ведёт до оффера",
      "Формы, тесты, созвоны — в задачах",
    ],
  },
  {
    id: "month",
    name: "Месяц",
    price: "3 000 ₸",
    period: "в месяц",
    sub: "Полный автопилот. Агент-ответчик уже включён.",
    popular: true,
    feats: [
      "До 100 откликов в день",
      "Всё из «Спринта»",
      "Приоритетная обработка чатов",
      "Авто-продление · отмена в 1 клик",
    ],
  },
];

const PLAN_LABELS: Record<string, string> = {
  free: "Бесплатный",
  active: "Активная подписка",
  cancelled: "Отменена · доступ до конца периода",
};

export default function BillingPage() {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await apiFetch<BillingStatus>("/api/billing/status"));
    } catch (e) {
      pushToast({ kind: "error", title: e instanceof Error ? e.message : "status failed" });
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // Оплата целиком на стороне Polar (merchant of record): никакого виджета и
  // никаких карточных данных у нас на странице — только редирект.
  async function subscribe(planId: string) {
    setBusy(planId);
    try {
      const { checkout_url } = await apiFetch<SubscribeResponse>(
        `/api/billing/subscribe?plan=${planId}`,
        { method: "POST" },
      );
      window.location.href = checkout_url;
    } catch (e) {
      pushToast({ kind: "error", title: e instanceof Error ? e.message : "subscribe failed" });
      setBusy(null);
    }
  }

  // Отмена, смена карты и счета живут в портале Polar — раньше «отмена» лишь
  // переключала колонку, а реальное списание останавливали руками.
  async function openPortal() {
    setBusy("portal");
    try {
      const { portal_url } = await apiFetch<PortalResponse>("/api/billing/portal", {
        method: "POST",
      });
      window.location.href = portal_url;
    } catch (e) {
      pushToast({ kind: "error", title: e instanceof Error ? e.message : "portal failed" });
      setBusy(null);
    }
  }

  const plan = status?.plan ?? "…";
  const isActive = plan === "active";

  return (
    <>
      <PageHeader title="Подписка" subtitle="план, оплата и история платежей" crumbs={[{ label: "Главная", href: "/dashboard" }, { label: "Аккаунт", href: "/account" }, { label: "Подписка" }]} />
      {status && !status.has_access && (
        <div
          style={{
            background: "var(--yellow-soft, #fdf3d0)",
            color: "var(--ink)",
            borderRadius: 14,
            padding: "12px 16px",
            marginBottom: 18,
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          Вы на бесплатном тарифе: отклики отправляются вручную по кнопке «прогнать
          пачку», всего 30 штук. Подписка включает автономный режим — агент работает,
          пока вы спите.
        </div>
      )}

      <Card style={{ marginBottom: 18 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 14,
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div>
            <div style={{ fontSize: 12, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>
              текущий статус
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 2 }}>{PLAN_LABELS[plan] ?? plan}</div>
          </div>
          <Tag tone={status?.has_access ? "ok" : "neutral"} dot>
            {status?.has_access ? "подписка активна" : "бесплатный тариф"}
          </Tag>
        </div>
        {status?.plan_expires_at && <Row k="действует до" v={fmtDate(status.plan_expires_at)} />}
        {status?.next_charge_at && <Row k="следующее списание" v={fmtDate(status.next_charge_at)} />}
        {(isActive || plan === "cancelled") && (
          <div style={{ marginTop: 16 }}>
            <Btn kind="coral" size="sm" onClick={openPortal} disabled={busy === "portal"}>
              {busy === "portal" ? "открываем…" : "управлять подпиской"}
            </Btn>
          </div>
        )}
      </Card>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
          gap: 18,
          marginBottom: 18,
          alignItems: "stretch",
        }}
      >
        {PLANS.map((p) => (
          <PlanCard
            key={p.id}
            plan={p}
            busy={busy === p.id}
            disabled={busy !== null}
            cta={isActive ? "сменить план" : "оформить"}
            onSubscribe={() => subscribe(p.id)}
          />
        ))}
      </div>

      <Card>
        <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>История платежей</div>
        {!status ? (
          <p style={{ color: "var(--muted)", fontSize: 13 }}>загрузка…</p>
        ) : status.history.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: 13 }}>платежей пока нет</p>
        ) : (
          <div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 100px 120px",
                gap: 14,
                padding: "8px 0",
                fontSize: 11,
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: 0.5,
                borderBottom: "1px solid var(--line-2)",
              }}
            >
              <div>дата</div>
              <div>сумма</div>
              <div>статус</div>
            </div>
            {status.history.map((p) => (
              <div
                key={p.provider_payment_id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 100px 120px",
                  gap: 14,
                  padding: "12px 0",
                  fontSize: 13,
                  borderBottom: "1px solid var(--line-2)",
                }}
              >
                <div>{fmtDate(p.created_at)}</div>
                <div className="mono">{p.amount ?? "—"}</div>
                <div>{p.status}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}

function PlanCard({
  plan,
  busy,
  disabled,
  cta,
  onSubscribe,
}: {
  plan: Plan;
  busy: boolean;
  disabled: boolean;
  cta: string;
  onSubscribe: () => void;
}) {
  const dark = !!plan.popular;
  return (
    <Card
      tone={dark ? "dark" : "light"}
      style={{
        padding: 28,
        height: "100%",
        display: "flex",
        flexDirection: "column",
        border: dark ? "none" : "1px solid var(--line-2)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: dark ? "#F5F1E6" : "var(--ink)" }}>
          {plan.name}
        </span>
        {plan.popular && <Tag tone="yellow">★ популярный</Tag>}
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span
          style={{
            fontSize: 34,
            fontWeight: 800,
            letterSpacing: -1,
            color: dark ? "#F5F1E6" : "var(--ink)",
          }}
        >
          {plan.price}
        </span>
        <span style={{ fontSize: 14, color: dark ? "#ffffff80" : "var(--muted)" }}>
          {plan.period}
        </span>
      </div>

      <p
        style={{
          fontSize: 13,
          lineHeight: 1.5,
          margin: "10px 0 20px",
          color: dark ? "#ffffff99" : "var(--muted)",
        }}
      >
        {plan.sub}
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1 }}>
        {plan.feats.map((f) => (
          <div key={f} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <ICheck size={14} stroke={dark ? "var(--yellow)" : "var(--ok)"} />
            <span style={{ fontSize: 13, lineHeight: 1.4, color: dark ? "#F5F1E6" : "var(--ink)" }}>
              {f}
            </span>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 22 }}>
        <Btn
          kind={dark ? "yellow" : "primary"}
          size="md"
          icon={<IBolt size={14} />}
          onClick={onSubscribe}
          disabled={disabled}
          style={{ width: "100%", justifyContent: "center" }}
        >
          {busy ? "открываем…" : cta}
        </Btn>
      </div>
    </Card>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", fontSize: 13 }}>
      <span style={{ color: "var(--muted)" }}>{k}</span>
      <span style={{ fontWeight: 600 }}>{v}</span>
    </div>
  );
}
