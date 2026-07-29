"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useNavCounts } from "@/hooks/useNavCounts";
import { formatBadge } from "@/lib/nav-counts";
import { apiFetch } from "@/lib/api";
import { IconBtn, LinkBtn } from "@/components/otclick/ui";
import { useQuery } from "@tanstack/react-query";
import {
  IHome, IList, IMail, IDoc, IUser, ISettings, ILogo, ILogout,
  ITelegram, IBolt, IChevRight, IChart,
} from "@/components/otclick/icons";

const STORAGE_KEY = "oc-sidebar-collapsed";

type Item = {
  id: string;
  href: string;
  icon: React.ReactNode;
  label: string;
  badge?: "chats" | "todo" | "notifications";
};

const NAV: Item[] = [
  { id: "dashboard", href: "/dashboard", icon: <IHome />, label: "Главная" },
  { id: "applications", href: "/applications", icon: <IList />, label: "Отклики" },
  { id: "analytics", href: "/analytics", icon: <IChart />, label: "Аналитика" },
  { id: "chats", href: "/chats", icon: <IMail />, label: "Чаты", badge: "chats" },
  { id: "todo", href: "/todo", icon: <IDoc />, label: "Задания", badge: "todo" },
  { id: "account", href: "/account", icon: <IUser />, label: "Аккаунт" },
];

export default function Sidebar({ email }: { email: string | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createClient();
  const counts = useNavCounts();
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  const { data: billing, isPending: billingPending } = useQuery({
    queryKey: ["billing-status"],
    queryFn: () => apiFetch<{ plan: string }>("/api/billing/status"),
    staleTime: 60_000,
  });

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "1");
    setMounted(true);
  }, []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      return next;
    });
  }

  async function signOut() {
    await supabase.auth.signOut();
    router.push("/auth");
    router.refresh();
  }

  const initials = email ? email.split(/[@.]/)[0].slice(0, 2).toUpperCase() : "ME";
  // stay hidden until the plan is actually known, otherwise Pro flashes for subscribers
  const showPro = !billingPending && billing?.plan !== "active";

  return (
    <aside
      className={`oc-sidebar${collapsed ? " oc-sidebar--collapsed" : ""}`}
      style={{
        width: collapsed ? 76 : 216,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "stretch",
        padding: "20px 8px 24px",
        gap: 14,
        position: "sticky",
        top: 16,
        alignSelf: "flex-start",
        height: "calc(100vh - 32px)",
        // no animation on the first paint: the stored collapsed width is only known
        // after hydration, and sliding it would read as a glitch rather than intent
        transition: mounted ? "width var(--dur) var(--ease)" : "none",
      }}
    >
      <div
        className="oc-sidebar-logo"
        style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 6px 8px" }}
      >
        <Link href="/dashboard" aria-label="otclick — на главную" style={{ display: "inline-flex" }}>
          <ILogo size={36} />
        </Link>
        {!collapsed && <span style={{ fontWeight: 800, fontSize: 17 }}>otclick</span>}
        <span style={{ marginLeft: "auto" }}>
          <IconBtn
            label={collapsed ? "развернуть меню" : "свернуть меню"}
            icon={
              <IChevRight
                size={16}
                style={{ transform: collapsed ? "none" : "rotate(180deg)", transition: "transform var(--dur) var(--ease)" }}
              />
            }
            onClick={toggleCollapsed}
          />
        </span>
      </div>

      <nav
        className="oc-sidebar-nav"
        aria-label="Основная навигация"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--r-lg)",
          padding: 8,
          display: "flex",
          flexDirection: "column",
          gap: 4,
          boxShadow: "var(--sh-1)",
        }}
      >
        {NAV.map((it) => {
          const active = pathname.startsWith(it.href);
          const badge = it.badge ? formatBadge(counts[it.badge]) : null;
          return (
            <Link
              key={it.id}
              href={it.href}
              className="oc-nav-item"
              aria-current={active ? "page" : undefined}
              title={collapsed ? it.label : undefined}
            >
              <span className="oc-nav-item__icon">{it.icon}</span>
              <span className="oc-nav-item__label">{it.label}</span>
              {badge && (
                <span className="oc-nav-badge" aria-label={`${counts[it.badge!]} новых`}>
                  {badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="oc-sidebar-spacer" style={{ flex: 1 }} />

      <div
        className="oc-sidebar-secondary"
        style={{
          background: "var(--surface)",
          borderRadius: "var(--r-lg)",
          padding: 8,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {showPro && (
          <LinkBtn
            href="/billing"
            kind="yellow"
            size="sm"
            icon={<IBolt size={14} />}
            label={collapsed ? "Подписка Pro" : undefined}
            style={{ justifyContent: "center", marginBottom: 4 }}
          >
            {collapsed ? "" : "Pro"}
          </LinkBtn>
        )}
        <a
          href="https://t.me/UnixAuto"
          target="_blank"
          rel="noopener noreferrer"
          className="oc-nav-item"
        >
          <span className="oc-nav-item__icon"><ITelegram /></span>
          <span className="oc-nav-item__label">Поддержка</span>
        </a>
        <Link href="/account" className="oc-nav-item">
          <span className="oc-nav-item__icon"><ISettings /></span>
          <span className="oc-nav-item__label">Настройки</span>
        </Link>
        <button type="button" onClick={signOut} className="oc-nav-item">
          <span className="oc-nav-item__icon"><ILogout /></span>
          <span className="oc-nav-item__label">Выйти</span>
        </button>
      </div>

      <div
        className="oc-sidebar-avatar"
        title={email ?? ""}
        style={{
          width: 44,
          height: 44,
          borderRadius: 14,
          overflow: "hidden",
          background: "linear-gradient(135deg, var(--yellow) 0%, var(--coral) 100%)",
          display: "grid",
          placeItems: "center",
          fontWeight: 700,
          color: "var(--ink)",
          fontSize: 13,
          flexShrink: 0,
        }}
      >
        {initials}
      </div>
    </aside>
  );
}
