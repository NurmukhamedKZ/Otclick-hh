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
  form_approval: "info",
  cover_letter_written: "success",
  web_session_expired: "error",
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
  form_approval: "Анкета ждёт подтверждения",
  cover_letter_written: "ИИ написал сопроводительное",
  web_session_expired: "Сессия hh истекла - переподключите аккаунт",
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

export default function RealtimeBridge() {
  const supabase = useMemo(() => createClient(), []);

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
            pushToast({
              kind: TYPE_KIND[n.type] ?? "info",
              title,
              body: formatBody(n),
            });
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
