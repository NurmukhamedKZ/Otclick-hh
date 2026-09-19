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

  const current = status?.today_count ?? 0;
  const workerState = status?.state ?? "stopped";
  const running = workerState !== "stopped";

  return (
    <Card
      tone="light"
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        minHeight: 154,
      }}
    >
      <div>
        <div style={{ fontSize: 17, fontWeight: 700 }}>Отклики сегодня</div>
        <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 4, maxWidth: 190 }}>
          Счётчик отправленных откликов за текущий день.
        </div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 10 }}>
          {running ? "обработка включена" : "обработка остановлена"}
        </div>
      </div>
      <div
        style={{
          width: 130,
          height: 130,
          borderRadius: "50%",
          background: "var(--bg-deep)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          flexShrink: 0,
        }}
      >
        <div style={{ fontSize: 10, color: "var(--muted)", letterSpacing: 0.5 }}>сегодня</div>
        <div style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.1 }}>{current}</div>
        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>отправлено</div>
      </div>
    </Card>
  );
}
