"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { apiFetch } from "@/lib/api";
import { Btn, Card, Field, KeyHint, LinkBtn, PageHeader, Tag } from "@/components/otclick/ui";
import { ILink, IPower, IRefresh, ISearch, ITelegram } from "@/components/otclick/icons";
import { openCommandPalette } from "@/components/otclick/command-palette";

type Tab = "profile" | "integrations" | "danger";

type HHStatus = {
  connected: boolean;
  expires_at: string | null;
  last_refreshed_at: string | null;
  hh_user_id: string | null;
};

type BillingStatusShape = {
  plan: string;
  trial_ends: string | null;
  plan_expires_at: string | null;
  next_charge_at: string | null;
};

const TABS: { key: Tab; label: string }[] = [
  { key: "profile", label: "Профиль" },
  { key: "integrations", label: "Интеграции" },
  { key: "danger", label: "Опасная зона" },
];

export default function AccountPage() {
  const router = useRouter();
  const supabase = createClient();
  const [tab, setTab] = useState<Tab>("profile");
  const [email, setEmail] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [createdAt, setCreatedAt] = useState<string | null>(null);
  const [hh, setHH] = useState<HHStatus | null>(null);
  const [billing, setBilling] = useState<BillingStatusShape | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      setEmail(user?.email ?? null);
      setUserId(user?.id ?? null);
      setCreatedAt(user?.created_at ?? null);
    })();
    apiFetch<HHStatus>("/api/hh/status")
      .then(setHH)
      .catch((e) => setErr(e instanceof Error ? e.message : "hh status failed"));
    apiFetch<BillingStatusShape>("/api/billing/status")
      .then(setBilling)
      .catch(() => undefined);
  }, [supabase]);

  async function disconnectHH() {
    if (!confirm("Отключить hh аккаунт? Воркер остановится.")) return;
    try {
      await apiFetch("/api/hh/disconnect", { method: "POST" });
      const next = await apiFetch<HHStatus>("/api/hh/status");
      setHH(next);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "disconnect failed");
    }
  }

  async function refreshHH() {
    try {
      await apiFetch("/api/hh/refresh", { method: "POST" });
      const next = await apiFetch<HHStatus>("/api/hh/status");
      setHH(next);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "refresh failed");
    }
  }

  async function signOut() {
    await supabase.auth.signOut();
    router.push("/auth");
    router.refresh();
  }

  const hhConnected = hh?.connected;
  const hhTone = hhConnected ? "ok" : "err";
  const initials = email
    ? email.split(/[@.]/)[0].slice(0, 2).toUpperCase()
    : "ME";
  const memberSince = createdAt
    ? new Date(createdAt).toLocaleDateString("ru-RU", { month: "long", year: "numeric" })
    : null;
  const isPro = billing?.plan === "active";

  return (
    <>
      <PageHeader title="Аккаунт" subtitle="подключение hh и настройки" crumbs={[{ label: "Главная", href: "/dashboard" }, { label: "Аккаунт" }]}
        actions={<Btn kind="ghost" size="sm" icon={<ISearch size={15} />} onClick={openCommandPalette}>поиск <KeyHint>⌘K</KeyHint></Btn>}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 18, flexWrap: "wrap" }}>
        <div
          style={{
            width: 80,
            height: 80,
            borderRadius: 22,
            background: "linear-gradient(135deg, var(--yellow) 0%, var(--coral) 100%)",
            display: "grid",
            placeItems: "center",
            fontSize: 26,
            fontWeight: 800,
            color: "var(--ink)",
            flexShrink: 0,
          }}
        >
          {initials}
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontSize: 26, fontWeight: 700 }}>
            {email ?? userId ?? "пользователь"}
          </div>
          <div style={{ color: "var(--muted)", fontSize: 14, marginTop: 2 }}>
            {memberSince ? `с ${memberSince}` : "—"}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <Tag tone={isPro ? "dark" : "neutral"} dot>
              {isPro ? "pro" : "free"}
            </Tag>
            <Tag tone={hhTone} dot>
              {hhConnected ? "hh подключён" : "hh не подключён"}
            </Tag>
          </div>
        </div>
      </div>

      <div
        style={{
          display: "inline-flex",
          background: "var(--surface)",
          padding: 6,
          borderRadius: 999,
          marginBottom: 18,
          flexWrap: "wrap",
        }}
      >
        {TABS.map((t) => (
          <button
            type="button"
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              border: "none",
              padding: "8px 18px",
              borderRadius: 999,
              background: tab === t.key ? "var(--ink)" : "transparent",
              color: tab === t.key ? "#F5F1E6" : "var(--ink)",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {err && <p style={{ fontSize: 13, color: "var(--err)", marginBottom: 12 }}>{err}</p>}

      {tab === "profile" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))", gap: 18 }}>
          <Card>
            <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>Контакты</div>
            <Field label="email" value={email ?? "—"} />
            <Field label="user_id" value={userId ?? "—"} mono readonly />
            <Field label="часовой пояс" value={Intl.DateTimeFormat().resolvedOptions().timeZone} />
            <Field label="язык" value="Русский" />
          </Card>
          <Card tone="cream">
            <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>Уведомления</div>
            <p style={{ fontSize: 13, color: "var(--muted)" }}>
              Тонкая настройка типов уведомлений — скоро. Сейчас приходят все события воркера.
            </p>
            <ul
              style={{
                fontSize: 13,
                color: "var(--ink)",
                marginTop: 12,
                paddingLeft: 16,
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              <li>капча — обязательно</li>
              <li>дневной лимит</li>
              <li>ошибки worker&apos;а</li>
            </ul>
          </Card>
        </div>
      )}

      {tab === "integrations" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))", gap: 18 }}>
          <Card tone="dark">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 14,
              }}
            >
              <div style={{ fontSize: 17, fontWeight: 700 }}>hh.ru</div>
              <Tag tone={hhConnected ? "ok" : "err"} dot>
                {hhConnected ? "подключён" : "нет связи"}
              </Tag>
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                fontSize: 13,
                color: "#ffffff80",
                marginBottom: 16,
              }}
            >
              <Row k="hh user_id" v={hh?.hh_user_id ?? "—"} />
              <Row
                k="токен"
                v={
                  hh?.expires_at ? `до ${new Date(hh.expires_at).toLocaleString("ru-RU")}` : "—"
                }
              />
              <Row
                k="последнее обновление"
                v={
                  hh?.last_refreshed_at
                    ? new Date(hh.last_refreshed_at).toLocaleString("ru-RU")
                    : "—"
                }
              />
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {hhConnected ? (
                <>
                  <Btn kind="yellow" size="sm" icon={<IRefresh size={14} />} onClick={refreshHH}>
                    refresh token
                  </Btn>
                  <LinkBtn href="/onboarding" kind="ghostDark" size="sm" icon={<ILink size={14} />}>
                    переподключить
                  </LinkBtn>
                  <Btn kind="ghostDark" size="sm" icon={<IPower size={14} />} onClick={disconnectHH}>
                    отключить
                  </Btn>
                </>
              ) : (
                <LinkBtn href="/onboarding" kind="yellow" size="sm">
                  подключить
                </LinkBtn>
              )}
            </div>
          </Card>
          <Card>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 14,
              }}
            >
              <div style={{ fontSize: 17, fontWeight: 700 }}>Telegram</div>
              <Tag tone="neutral">не подключён</Tag>
            </div>
            <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 18 }}>
              Уведомления о капче и ошибках прямо в Telegram. В разработке.
            </div>
            <Btn kind="primary" icon={<ITelegram size={14} />} disabled>
              скоро
            </Btn>
          </Card>
        </div>
      )}

      {tab === "danger" && (
        <Card>
          <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Опасная зона</div>
          <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 22 }}>
            Эти действия нельзя отменить. Хорошо подумай.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <DangerRow
              title="Выйти из аккаунта"
              sub="можно вернуться в любой момент"
              btnLabel="Выйти"
              onClick={signOut}
            />
            <DangerRow
              title="Удалить аккаунт"
              sub="навсегда удалит данные, отклики, токены hh"
              btnLabel="Удалить"
              tone="err"
              disabled
            />
          </div>
        </Card>
      )}
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
      <span>{k}</span>
      <span
        style={{
          color: "#F5F1E6",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 12,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          maxWidth: 220,
        }}
      >
        {v}
      </span>
    </div>
  );
}

function DangerRow({
  title,
  sub,
  btnLabel,
  tone,
  disabled,
  onClick,
}: {
  title: string;
  sub: string;
  btnLabel: string;
  tone?: "err";
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "14px 16px",
        borderRadius: 14,
        background: "var(--bg-deep)",
        flexWrap: "wrap",
      }}
    >
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{sub}</div>
      </div>
      <Btn
        kind={tone === "err" ? "coral" : "ghost"}
        size="sm"
        disabled={disabled}
        onClick={onClick}
        style={disabled ? { opacity: 0.5, cursor: "not-allowed" } : undefined}
      >
        {btnLabel}
      </Btn>
    </div>
  );
}
