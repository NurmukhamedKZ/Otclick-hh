"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { apiFetch } from "@/lib/api";
import type { CaptchaRequest } from "@/lib/types";
import { Btn, Card } from "@/components/otclick/ui";
import { IClose, IExternal, IShield } from "@/components/otclick/icons";

const SCREENSHOT_BUCKET = "captcha-screenshots";

const EVENT = "oc:open-captcha-modal";

export function openCaptchaModal() {
  window.dispatchEvent(new CustomEvent(EVENT));
}

export default function CaptchaModal() {
  const [pending, setPending] = useState<CaptchaRequest | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [forcedOpen, setForcedOpen] = useState(false);
  const supabase = useMemo(() => createClient(), []);

  useEffect(() => {
    function show() { setForcedOpen(true); }
    window.addEventListener(EVENT, show);
    return () => window.removeEventListener(EVENT, show);
  }, []);

  const refreshImage = useCallback(async (row: CaptchaRequest) => {
    if (!row.storage_path) {
      setImageUrl(null);
      return;
    }
    const { data } = await supabase.storage
      .from(SCREENSHOT_BUCKET)
      .createSignedUrl(row.storage_path, 300);
    setImageUrl(data?.signedUrl ?? null);
  }, [supabase]);

  useEffect(() => {
    if (!forcedOpen) return;
    setForcedOpen(false);
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      const { data } = await supabase
        .from("captcha_requests")
        .select("*")
        .eq("user_id", user.id)
        .eq("solved", false)
        .order("created_at", { ascending: false })
        .limit(1);
      const row = (data?.[0] ?? null) as CaptchaRequest | null;
      if (row) { setPending(row); if (row.storage_path) refreshImage(row); }
    })();
  }, [forcedOpen, supabase, refreshImage]);

  useEffect(() => {
    let cancelled = false;
    let channel: ReturnType<typeof supabase.channel> | null = null;

    async function loadPending(userId: string) {
      const { data, error } = await supabase
        .from("captcha_requests")
        .select("*")
        .eq("user_id", userId)
        .eq("solved", false)
        .order("created_at", { ascending: false })
        .limit(1);
      if (error || cancelled) return;
      const row = (data?.[0] ?? null) as CaptchaRequest | null;
      setPending(row);
      if (row) refreshImage(row);
      else setImageUrl(null);
    }

    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;
      await loadPending(user.id);

      const filter = `user_id=eq.${user.id}`;
      channel = supabase
        .channel("captcha-feed")
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "captcha_requests", filter },
          (payload) => {
            const row = payload.new as CaptchaRequest;
            if (!row.solved) {
              setPending(row);
              refreshImage(row);
            }
          },
        )
        .on(
          "postgres_changes",
          { event: "UPDATE", schema: "public", table: "captcha_requests", filter },
          (payload) => {
            const row = payload.new as CaptchaRequest;
            setPending((prev) => {
              if (!prev || prev.id !== row.id) return prev;
              if (row.solved) {
                setImageUrl(null);
                return null;
              }
              return row;
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

  async function handleSolve() {
    if (!pending) return;
    try {
      await apiFetch(`/api/captcha/${pending.id}/solve`, { method: "POST" });
    } catch {
      /* best-effort */
    }
  }

  async function handleDismiss() {
    const id = pending?.id;
    setPending(null);
    setImageUrl(null);
    setForcedOpen(false);
    if (!id) return;
    try {
      await apiFetch(`/api/captcha/${id}/dismiss`, { method: "POST" });
    } catch {
      /* best-effort */
    }
  }

  if (!pending) return null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(26,27,31,0.5)",
        backdropFilter: "blur(4px)",
        zIndex: 60,
        display: "grid",
        placeItems: "center",
        padding: 20,
        animation: "oc-fadein .2s ease",
      }}
    >
      <Card tone="light" style={{ width: "min(440px, 100%)", padding: 28, position: "relative" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 18 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 14,
              flexShrink: 0,
              background: "var(--coral-soft)",
              color: "var(--coral)",
              display: "grid",
              placeItems: "center",
            }}
          >
            <IShield size={20} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>hh просит решить капчу</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
              Бот поставлен на паузу. Реши капчу на hh — worker подхватит сам.
            </div>
          </div>
          <button
            type="button"
            onClick={handleDismiss}
            aria-label="close"
            style={{
              width: 32,
              height: 32,
              borderRadius: 10,
              border: "none",
              background: "var(--bg-deep)",
              display: "grid",
              placeItems: "center",
              cursor: "pointer",
              color: "var(--ink)",
            }}
          >
            <IClose size={16} />
          </button>
        </div>

        {imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageUrl}
            alt="captcha screenshot"
            style={{
              width: "100%",
              maxHeight: 280,
              objectFit: "contain",
              borderRadius: 14,
              border: "1px solid var(--line)",
              marginBottom: 14,
              background: "var(--bg-deep)",
            }}
          />
        ) : (
          <div
            style={{
              height: 100,
              borderRadius: 14,
              background: "var(--bg-deep)",
              display: "grid",
              placeItems: "center",
              marginBottom: 14,
              color: "var(--muted)",
              fontSize: 13,
            }}
          >
            скриншот грузится…
          </div>
        )}

        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          {pending.captcha_url && (
            <a
              href={pending.captcha_url}
              target="_blank"
              rel="noreferrer"
              style={{
                background: "var(--ink)",
                color: "#fff",
                padding: "10px 16px",
                borderRadius: 999,
                fontSize: 14,
                fontWeight: 600,
                textDecoration: "none",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              открыть на hh <IExternal size={13} />
            </a>
          )}
          <Btn kind="ghost" onClick={handleSolve}>
            я решил, проверить
          </Btn>
          <Btn kind="ghost" onClick={handleDismiss}>
            закрыть
          </Btn>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 11,
            color: "var(--muted)",
          }}
        >
          <span>создано {new Date(pending.created_at).toLocaleTimeString()}</span>
        </div>
      </Card>
    </div>
  );
}
