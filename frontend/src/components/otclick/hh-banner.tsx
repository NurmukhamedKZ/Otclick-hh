"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Banner, Skeleton } from "@/components/otclick/ui";

type HHStatus = {
  connected: boolean;
  expires_at: string | null;
  last_refreshed_at: string | null;
  hh_user_id: string | null;
};

function classify(s: HHStatus | null): "ok" | "warn" | "err" | null {
  if (!s) return null;
  if (!s.connected) return "err";
  if (s.expires_at) {
    const t = new Date(s.expires_at).getTime();
    if (t - Date.now() < 24 * 3600 * 1000) return "warn";
  }
  return "ok";
}

export default function HHBanner() {
  const [status, setStatus] = useState<HHStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<HHStatus>("/api/hh/status")
      .then(setStatus)
      .catch((e) => setError(e instanceof Error ? e.message : "status failed"));
  }, []);

  if (error) {
    return (
      <Banner tone="err" title="hh status" description={error} />
    );
  }

  const kind = classify(status);
  if (!kind || kind === "ok") {
    if (kind === "ok") return null;
    return <Skeleton h={50} radius="var(--r-md)" />;
  }

  if (kind === "warn") {
    return (
      <Banner
        tone="warn"
        title="токен скоро истечёт"
        description="мы обновим его автоматически"
      />
    );
  }

  return (
    <Banner
      tone="err"
      title="нет связи с hh"
      description="переподключи аккаунт, чтобы продолжить"
      action={{ label: "Переподключить", href: "/onboarding" }}
    />
  );
}
