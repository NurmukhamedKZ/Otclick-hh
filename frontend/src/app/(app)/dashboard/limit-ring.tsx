"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { WorkerStatus } from "@/lib/types";
import { Card } from "@/components/otclick/ui";

export default function LimitRing() {
  const { data: status } = useQuery({
    queryKey: ["worker-status"],
    queryFn: () => apiFetch<WorkerStatus>("/api/worker/status"),
    refetchInterval: 15000,
  });

  const goal = status?.daily_limit ?? 30;
  const current = status?.today_count ?? 0;
  const pct = goal > 0 ? Math.min(current / goal, 1) : 0;
  const C = 2 * Math.PI * 52;

  return (
    <Card tone="light" interactive={{ href: "/billing" }} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <div>
        <div style={{ fontSize: 17, fontWeight: 700 }}>Лимит на сегодня</div>
        <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 4, maxWidth: 160 }}>
          Бот сам остановится при достижении лимита
        </div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
          нужно больше — открыть тарифы →
        </div>
      </div>
      <div style={{ position: "relative", width: 130, height: 130 }}>
        <svg width="130" height="130" viewBox="0 0 130 130">
          <circle cx="65" cy="65" r="52" stroke="var(--bg-deep)" strokeWidth="10" fill="none" />
          <circle
            cx="65"
            cy="65"
            r="52"
            stroke="var(--coral)"
            strokeWidth="10"
            fill="none"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - pct)}
            strokeLinecap="round"
            transform="rotate(-90 65 65)"
          />
        </svg>
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          <div style={{ fontSize: 10, color: "var(--muted)", letterSpacing: 0.5 }}>цель</div>
          <div style={{ fontSize: 26, fontWeight: 800, lineHeight: 1 }}>{goal}</div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
            {current} отправлено
          </div>
        </div>
      </div>
    </Card>
  );
}
