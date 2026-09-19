"use client";

import { useEffect, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import { pushToast, type ToastKind } from "@/components/toaster";
import type { NotificationRow } from "@/lib/types";

const TYPE_KIND: Record<string, ToastKind> = {
  captcha: "warning",
  limit_reached: "warning",
  worker_stop: "info",
  token_dead: "error",
  account_banned: "error",
  resume_missing: "error",
  recruiter_todo: "info",
  recruiter_draft: "info",
  recruiter_question: "info",
  form_approval: "info",
  cover_letter_written: "success",
  web_session_expired: "error",
  recruiter_error: "error",
};

const TYPE_TITLE: Record<string, string> = {
  captcha: "Нужна капча на hh",
  limit_reached: "Достигнут дневной лимит",
  worker_stop: "Worker остановлен",
  token_dead: "Токен hh умер — переподключи аккаунт",
  account_banned: "Аккаунт hh заблокирован",
  resume_missing: "Резюме недоступно",
  recruiter_todo: "Новая задача от рекрутёра",
  recruiter_draft: "Черновик ответа рекрутёру",
  recruiter_question: "ИИ-агент спрашивает вас",
  form_approval: "Анкета ждёт подтверждения",
  cover_letter_written: "ИИ написал сопроводительное",
  web_session_expired: "Сессия hh истекла - переподключите аккаунт",
  recruiter_error: "Ошибка ИИ-агента в чате с рекрутёром",
};

function formatBody(n: NotificationRow): string | undefined {
  if (!n.payload) return undefined;
  try {
    const parts = Object.entries(n.payload).map(([k, v]) => `${k}: ${String(v)}`);
    return parts.slice(0, 3).join(" · ");
  } catch {
    return undefined;
  }
}

function playBeep() {
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.35);
    osc.onended = () => ctx.close();
  } catch {
    // ignore — audio unsupported/blocked
  }
}

function notifyBrowser(title: string, body: string | undefined) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  new Notification(title, { body, icon: "/favicon.ico", tag: title });
}

export default function RealtimeBridge() {
  const supabase = useMemo(() => createClient(), []);

  useEffect(() => {
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let channel: ReturnType<typeof supabase.channel> | null = null;

    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;

      const filter = `user_id=eq.${user.id}`;
      channel = supabase
        .channel("notifications-toast")
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "notifications", filter },
          (payload) => {
            const n = payload.new as NotificationRow;
            const title = TYPE_TITLE[n.type] ?? n.type;
            const body = formatBody(n);
            pushToast({
              kind: TYPE_KIND[n.type] ?? "info",
              title,
              body,
            });
            playBeep();
            notifyBrowser(title, body);
          },
        )
        .subscribe();
    })();

    return () => {
      cancelled = true;
      if (channel) supabase.removeChannel(channel);
    };
  }, [supabase]);

  return null;
}
