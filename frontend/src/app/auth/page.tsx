"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Btn } from "@/components/otclick/ui";
import { IEye, ILock, ILogo, IMail } from "@/components/otclick/icons";

type Mode = "login" | "signup";

export default function AuthPage() {
  const router = useRouter();
  const supabase = createClient();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const googleAuthEnabled = process.env.NEXT_PUBLIC_GOOGLE_AUTH_ENABLED === "true";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    setLoading(true);
    if (mode === "login") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      setLoading(false);
      if (error) return setErr(error.message);
      router.push("/dashboard");
      router.refresh();
    } else {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: `${location.origin}/auth/callback` },
      });
      setLoading(false);
      if (error) return setErr(error.message);
      if (data.session) {
        router.push("/dashboard");
        router.refresh();
      } else {
        setMsg("Проверь почту — отправлена ссылка подтверждения.");
      }
    }
  }

  async function google() {
    setErr(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${location.origin}/auth/callback` },
    });
    if (error) setErr(error.message);
  }

  const isLogin = mode === "login";

  return (
    <div
      className="oc-auth-grid"
      style={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 0,
        position: "relative",
        zIndex: 1,
      }}
    >
      <div
        className="oc-auth-hero"
        style={{
          background: "var(--ink)",
          color: "#F5F1E6",
          padding: "32px 40px",
          display: "flex",
          flexDirection: "column",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <Link
          href="/"
          style={{
            background: "#ffffff10",
            color: "#F5F1E6",
            padding: "8px 14px",
            borderRadius: 999,
            fontSize: 13,
            fontWeight: 600,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            alignSelf: "flex-start",
            textDecoration: "none",
          }}
        >
          ← на главную
        </Link>
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            maxWidth: 460,
            marginLeft: 40,
          }}
        >
          <ILogo size={48} />
          <h1
            className="serif"
            style={{
              fontSize: 56,
              lineHeight: 1,
              margin: "24px 0 16px",
              fontWeight: 400,
            }}
          >
            Войди и забудь<br />про отклики
          </h1>
          <div style={{ color: "#ffffff80", fontSize: 16, lineHeight: 1.5 }}>
            Подключи hh, настрой фильтры один раз — дальше всё сам.
          </div>
          <div
            style={{
              position: "absolute",
              right: -80,
              top: 100,
              width: 200,
              height: 200,
              borderRadius: "50%",
              background: "var(--yellow)",
              opacity: 0.15,
              filter: "blur(40px)",
            }}
          />
          <div
            style={{
              position: "absolute",
              right: 40,
              bottom: 60,
              width: 140,
              height: 140,
              borderRadius: "50%",
              background: "var(--coral)",
              opacity: 0.2,
              filter: "blur(30px)",
            }}
          />
        </div>
      </div>

      <div
        style={{
          background: "var(--bg)",
          padding: 40,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
        }}
      >
        <div style={{ maxWidth: 380, width: "100%", margin: "0 auto" }}>
          <div
            style={{
              display: "inline-flex",
              background: "var(--surface)",
              padding: 6,
              borderRadius: 999,
              marginBottom: 24,
            }}
          >
            {(["login", "signup"] as const).map((id) => (
              <button
                type="button"
                key={id}
                onClick={() => setMode(id)}
                style={{
                  border: "none",
                  padding: "8px 22px",
                  borderRadius: 999,
                  fontSize: 14,
                  fontWeight: 600,
                  background: mode === id ? "var(--ink)" : "transparent",
                  color: mode === id ? "#F5F1E6" : "var(--ink)",
                  cursor: "pointer",
                }}
              >
                {id === "login" ? "войти" : "регистрация"}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 28, fontWeight: 700, marginBottom: 4 }}>
            {isLogin ? "С возвращением" : "Создай аккаунт"}
          </div>
          <div style={{ color: "var(--muted)", fontSize: 14, marginBottom: 24 }}>
            {isLogin ? "Бот соскучился" : "Это займёт 20 секунд"}
          </div>

          {googleAuthEnabled && (
            <button
              type="button"
              onClick={google}
              style={{
                width: "100%",
                padding: "12px 16px",
                borderRadius: 14,
                background: "#fff",
                border: "1px solid var(--line)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 10,
                fontSize: 14,
                fontWeight: 600,
                marginBottom: 16,
                cursor: "pointer",
                fontFamily: "inherit",
                color: "var(--ink)",
              }}
            >
              <svg width="18" height="18" viewBox="0 0 18 18">
                <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.79 2.72v2.26h2.9c1.7-1.57 2.69-3.88 2.69-6.62z" />
                <path fill="#34A853" d="M9 18c2.43 0 4.46-.8 5.95-2.18l-2.9-2.26c-.81.54-1.83.86-3.05.86-2.34 0-4.33-1.59-5.04-3.71H.96v2.33A9 9 0 0 0 9 18z" />
                <path fill="#FBBC05" d="M3.96 10.71A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.17.28-1.71V4.96H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.04l3-2.33z" />
                <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 9 0 9 9 0 0 0 .96 4.96l3 2.33C4.67 5.17 6.66 3.58 9 3.58z" />
              </svg>
              продолжить с google
            </button>
          )}

          {googleAuthEnabled && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                margin: "20px 0",
                color: "var(--muted)",
                fontSize: 12,
              }}
            >
              <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
              или email
              <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
            </div>
          )}

          <form onSubmit={submit}>
            <div style={{ position: "relative", marginBottom: 12 }}>
              <span style={{ position: "absolute", left: 16, top: 14, color: "var(--muted)" }}>
                <IMail size={16} />
              </span>
              <input
                type="email"
                required
                autoComplete="email"
                placeholder="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={{
                  width: "100%",
                  padding: "12px 16px 12px 44px",
                  borderRadius: 14,
                  border: "1px solid var(--line)",
                  background: "#fff",
                  outline: "none",
                  fontFamily: "inherit",
                  fontSize: 14,
                  color: "var(--ink)",
                }}
              />
            </div>
            <div style={{ position: "relative", marginBottom: 18 }}>
              <span style={{ position: "absolute", left: 16, top: 14, color: "var(--muted)" }}>
                <ILock size={16} />
              </span>
              <input
                type={showPw ? "text" : "password"}
                required
                minLength={isLogin ? undefined : 6}
                autoComplete={isLogin ? "current-password" : "new-password"}
                placeholder={isLogin ? "пароль" : "пароль (мин 6)"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  width: "100%",
                  padding: "12px 44px 12px 44px",
                  borderRadius: 14,
                  border: "1px solid var(--line)",
                  background: "#fff",
                  outline: "none",
                  fontFamily: "inherit",
                  fontSize: 14,
                  color: "var(--ink)",
                }}
              />
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                style={{
                  position: "absolute",
                  right: 16,
                  top: 14,
                  color: "var(--muted)",
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                <IEye size={16} />
              </button>
            </div>
            <Btn
              type="submit"
              kind="primary"
              size="lg"
              disabled={loading}
              style={{ width: "100%", justifyContent: "center" }}
            >
              {loading ? "…" : isLogin ? "войти" : "зарегистрироваться"} →
            </Btn>
          </form>

          {msg && <p style={{ marginTop: 18, fontSize: 13, color: "var(--ok)" }}>{msg}</p>}
          {err && <p style={{ marginTop: 18, fontSize: 13, color: "var(--err)" }}>{err}</p>}
        </div>
      </div>
    </div>
  );
}
