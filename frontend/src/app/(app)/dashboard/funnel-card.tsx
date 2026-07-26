"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Analytics } from "@/lib/types";
import { Card, Skeleton } from "@/components/otclick/ui";

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 1000) / 10}%`;
}

export default function FunnelCard() {
  const { data, isPending } = useQuery({
    queryKey: ["analytics", "30"],
    queryFn: () => apiFetch<Analytics>("/api/analytics?days=30"),
    staleTime: 60_000,
  });

  return (
    <Card tone="cream" interactive={{ href: "/analytics" }} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <div style={{ fontSize: 17, fontWeight: 700 }}>Конверсия за 30 дней</div>
        <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 4 }}>
          вся аналитика — открыть →
        </div>
      </div>
      {isPending ? (
        <Skeleton h={44} />
      ) : (
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.1 }}>{pct(data?.kpi.invite_rate)}</div>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>на собеседование</div>
          </div>
          <div>
            <div style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.1 }}>{pct(data?.kpi.reply_rate)}</div>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>ответ работодателя</div>
          </div>
          <div>
            <div style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.1 }}>{data?.funnel.sent ?? 0}</div>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>откликов</div>
          </div>
        </div>
      )}
    </Card>
  );
}
