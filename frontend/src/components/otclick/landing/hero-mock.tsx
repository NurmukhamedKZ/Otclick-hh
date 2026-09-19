"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { Tag } from "@/components/otclick/ui";
import { Float } from "./motion";

const LETTER =
  "Добрый день! Прочитал описание — у вас стек на Python/FastAPI с переходом на Go. Это совпадает с моим опытом за последние 3 года…";

const SENT = [
  { c: "var(--yellow)", t: "Senior Frontend · Тинькофф" },
  { c: "var(--coral)", t: "Backend Go · Авито" },
  { c: "var(--ink)", t: "ML-инженер · Яндекс" },
];

/* typewriter that loops the cover-letter text */
function useTypewriter(text: string, enabled: boolean) {
  const [n, setN] = useState(enabled ? 0 : text.length);
  useEffect(() => {
    if (!enabled) return;
    let i = 0;
    let hold = 0;
    const id = setInterval(() => {
      if (i <= text.length) {
        setN(i);
        i += 1;
      } else {
        // pause at full text, then restart
        hold += 1;
        if (hold > 28) {
          i = 0;
          hold = 0;
        }
      }
    }, 38);
    return () => clearInterval(id);
  }, [text, enabled]);
  return text.slice(0, n);
}

export function HeroMock() {
  const reduce = useReducedMotion();
  const typed = useTypewriter(LETTER, !reduce);
  const [sentCount, setSentCount] = useState(reduce ? 3 : 0);

  // reveal "sent" rows one by one
  useEffect(() => {
    if (reduce) return;
    let i = 0;
    const id = setInterval(() => {
      i = i >= SENT.length ? 1 : i + 1;
      setSentCount(i);
    }, 1400);
    return () => clearInterval(id);
  }, [reduce]);

  return (
    <div style={{ position: "relative", width: "100%", maxWidth: 460, margin: "0 auto" }}>
      {/* glow behind */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: "-12% -8% -8% -12%",
          background:
            "radial-gradient(60% 55% at 70% 30%, var(--yellow-soft), transparent 70%), radial-gradient(50% 50% at 20% 80%, var(--coral-soft), transparent 70%)",
          filter: "blur(28px)",
          opacity: 0.7,
          zIndex: 0,
        }}
      />

      {/* main letter card */}
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 30, rotateX: 8 }}
        animate={reduce ? undefined : { opacity: 1, y: 0, rotateX: 0 }}
        transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
        style={{
          position: "relative",
          zIndex: 1,
          background: "var(--surface)",
          borderRadius: 24,
          padding: 22,
          boxShadow: "0 30px 60px -22px rgba(26,27,31,0.32)",
          border: "1px solid var(--line-2)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            color: "var(--coral)",
            fontSize: 11,
            fontWeight: 700,
            marginBottom: 14,
          }}
        >
          <span style={{ fontSize: 14 }}>✨</span> otclick пишет сопроводительное
        </div>

        <div
          style={{
            background: "var(--ink)",
            color: "#F5F1E6",
            padding: 18,
            borderRadius: 16,
            fontSize: 13.5,
            lineHeight: 1.6,
            minHeight: 132,
          }}
        >
          {typed}
          {!reduce && (
            <motion.span
              animate={{ opacity: [1, 0, 1] }}
              transition={{ duration: 0.9, repeat: Infinity }}
              style={{
                display: "inline-block",
                width: 2,
                height: 15,
                background: "var(--yellow)",
                marginLeft: 2,
                verticalAlign: -2,
              }}
            />
          )}
        </div>

        {/* applied rows */}
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
          <AnimatePresence initial={false}>
            {SENT.slice(0, sentCount).map((r) => (
              <motion.div
                key={r.t}
                layout
                initial={reduce ? false : { opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  background: "var(--bg-deep)",
                  borderRadius: 12,
                  padding: "9px 12px",
                }}
              >
                <span
                  style={{
                    width: 26,
                    height: 26,
                    borderRadius: 999,
                    background: r.c,
                    flexShrink: 0,
                  }}
                />
                <span style={{ flex: 1, fontSize: 12.5, fontWeight: 700 }}>{r.t}</span>
                <Tag tone="ok" dot>
                  отклик
                </Tag>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </motion.div>

      {/* floating: offers counter */}
      <Float
        range={10}
        duration={4.5}
        style={{ position: "absolute", top: -22, right: -14, zIndex: 2 }}
      >
        <div
          style={{
            background: "var(--yellow)",
            color: "var(--ink)",
            borderRadius: 16,
            padding: "12px 16px",
            boxShadow: "0 18px 36px -14px rgba(245,203,61,0.7)",
            border: "1px solid #00000010",
          }}
        >
          <div style={{ fontSize: 10, fontWeight: 700, opacity: 0.65 }}>ПРИГЛАШЕНИЙ</div>
          <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: -1, lineHeight: 1 }}>
            +12
          </div>
        </div>
      </Float>

      {/* floating: recruiter ping */}
      <Float
        range={9}
        duration={5.2}
        delay={0.6}
        style={{ position: "absolute", bottom: -18, left: -18, zIndex: 2 }}
      >
        <div
          style={{
            background: "var(--surface)",
            borderRadius: 14,
            padding: "10px 14px",
            boxShadow: "0 18px 36px -16px rgba(26,27,31,0.4)",
            border: "1px solid var(--line-2)",
            display: "flex",
            alignItems: "center",
            gap: 10,
            maxWidth: 220,
          }}
        >
          <span
            style={{
              width: 30,
              height: 30,
              borderRadius: 999,
              background: "var(--coral)",
              color: "#fff",
              display: "grid",
              placeItems: "center",
              fontWeight: 800,
              fontSize: 12,
              flexShrink: 0,
            }}
          >
            Я
          </span>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>Анна · Яндекс</div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Созвон в четверг?</div>
          </div>
        </div>
      </Float>
    </div>
  );
}
