"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createClient } from "@/lib/supabase/client";
import { apiFetch } from "@/lib/api";
import type { WorkerStatus } from "@/lib/types";
import { Card } from "@/components/otclick/ui";

function startOfWeek(d: Date): Date {
  const dt = new Date(d);
  const day = (dt.getDay() + 6) % 7;
  dt.setHours(0, 0, 0, 0);
  dt.setDate(dt.getDate() - day);
  return dt;
}

function fmt(d: Date): string {
  const days = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
  return `${days[d.getDay()]} ${d.getDate()}`;
}

export default function WeeklyPlan() {
  const supabase = useMemo(() => createClient(), []);
  const { data: status } = useQuery({
    queryKey: ["worker-status"],
    queryFn: () => apiFetch<WorkerStatus>("/api/worker/status"),
    refetchInterval: 30000,
  });
  const [weekSent, setWeekSent] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const start = startOfWeek(new Date());
      // Note: supabase-js sends a HEAD request for `head: true`, but the local
      // shim does not implement HEAD (returns 405 → count is undefined → 0).
      // Use a real GET with count=exact: the shim honours Prefer: count=exact
      // and returns the total in content-range, while still shipping rows.
      // We select only `id` to keep the payload tiny.
      const { count } = await supabase
        .from("applications")
        .select("id", { count: "exact" })
        .gte("created_at", start.toISOString())
        .in("status", ["sent", "form_sent"]);
      if (cancelled) return;
      setWeekSent(count ?? 0);
    })();
    return () => {
      cancelled = true;
    };
  }, [supabase]);

  const dailyLimit = status?.daily_limit ?? 30;
  const goal = dailyLimit * 7;
  const pct = goal > 0 ? Math.min(weekSent / goal, 1) : 0;
  const start = startOfWeek(new Date());
  const end = new Date(start);
  end.setDate(start.getDate() + 6);

  return (
    <Card tone="light">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ fontSize: 17, fontWeight: 700 }}>Недельный план</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
          <span style={{ fontSize: 22, fontWeight: 800 }}>
            {Math.round(pct * 100)}
            <span style={{ fontSize: 14 }}>%</span>
          </span>
          <span style={{ fontSize: 11, color: "var(--muted)" }}>выполнено</span>
        </div>
      </div>
      <div style={{ position: "relative", marginTop: 22 }}>
        <div
          style={{
            position: "absolute",
            left: `calc(${Math.round(pct * 100)}% - 24px)`,
            top: -22,
            background: "var(--ink)",
            color: "#F5F1E6",
            padding: "3px 9px",
            borderRadius: 999,
            fontSize: 11,
            fontWeight: 600,
            whiteSpace: "nowrap",
          }}
        >
          {weekSent} / {goal}
        </div>
        <div
          style={{
            height: 10,
            background: "var(--bg-deep)",
            borderRadius: 999,
            position: "relative",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: `${Math.round(pct * 100)}%`,
              background: "var(--ink)",
              borderRadius: 999,
            }}
          />
        </div>
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: 10,
          fontSize: 12,
          color: "var(--muted)",
        }}
      >
        <span className="mono">{fmt(start)}</span>
        <span className="mono">{fmt(end)}</span>
      </div>
    </Card>
  );
}
