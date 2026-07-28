"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { Btn, Card } from "@/components/otclick/ui";
import type { BillingStatus } from "@/lib/types";

// Polar редиректит сюда сразу после оплаты, а план активирует вебхук — он может
// прийти на секунду позже. Поэтому поллим статус, а не показываем «не оплачено».
const POLL_MS = 2000;
const MAX_ATTEMPTS = 15; // ~30 секунд

export default function BillingSuccessPage() {
  const [active, setActive] = useState(false);
  const [gaveUp, setGaveUp] = useState(false);

  useEffect(() => {
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;

    async function poll() {
      if (cancelled) return;
      try {
        const status = await apiFetch<BillingStatus>("/api/billing/status");
        if (status.has_access) {
          setActive(true);
          return;
        }
      } catch {
        // сеть моргнула — просто пробуем ещё раз
      }
      attempts += 1;
      if (attempts >= MAX_ATTEMPTS) {
        setGaveUp(true);
        return;
      }
      timer = setTimeout(poll, POLL_MS);
    }

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return (
    <>
      <Card>
        <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 8 }}>
          {active ? "Тариф активирован" : "Платёж принят"}
        </div>
        <p style={{ color: "var(--muted)", fontSize: 14, lineHeight: 1.6, marginBottom: 18 }}>
          {active
            ? "Автономный режим включён — автоотклик можно запускать, он больше не остановится после одной пачки."
            : gaveUp
              ? "Платёж принят, но подтверждение от платёжной системы ещё не дошло. Обычно это занимает до минуты — обновите страницу подписки чуть позже. Если через 10 минут тариф не активен, напишите нам."
              : "Активируем тариф — это занимает несколько секунд."}
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link href="/dashboard" style={{ textDecoration: "none" }}>
            <Btn kind="primary" size="sm">
              на главную
            </Btn>
          </Link>
          <Link href="/billing" style={{ textDecoration: "none" }}>
            <Btn kind="ghost" size="sm">
              статус подписки
            </Btn>
          </Link>
        </div>
      </Card>
    </>
  );
}
