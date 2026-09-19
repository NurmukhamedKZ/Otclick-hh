"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { Tag } from "@/components/otclick/ui";
import { Float } from "./motion";

const LETTER =
  "Добрый день. В вакансии важны масштабирование ИТ-функции, целевая архитектура и цифровизация операций. В моём опыте есть сопоставимые задачи…";

const REVIEWED = [
  { c: "var(--yellow)", t: "IT Director · Логистика", score: "86/100" },
  { c: "var(--coral)", t: "CDTO · Производство", score: "82/100" },
  { c: "var(--ink)", t: "CIO · FMCG", score: "79/100" },
];

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
  const [reviewedCount, setReviewedCount] = useState(reduce ? REVIEWED.length : 0);

  useEffect(() => {
    if (reduce) return;

    let i = 0;
    const id = setInterval(() => {
      i = i >= REVIEWED.length ? 1 : i + 1;
      setReviewedCount(i);
    }, 1400);

    return () => clearInterval(id);
  }, [reduce]);

  return (
    <div style={{ position: "relative", width: "100%", maxWidth: 460, margin: "0 auto" }}>
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
          <span style={{ fontSize: 14 }}>✦</span> пример сопроводительного
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

        <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
          <AnimatePresence initial={false}>
            {REVIEWED.slice(0, reviewedCount).map((row) => (
              <motion.div
                key={row.t}
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
                    background: row.c,
                    flexShrink: 0,
                  }}
                />
                <span style={{ flex: 1, fontSize: 12.5, fontWeight: 700 }}>{row.t}</span>
                <span style={{ fontSize: 11.5, color: "var(--muted)", fontWeight: 700 }}>
                  {row.score}
                </span>
                <Tag tone="ok" dot>
                  review
                </Tag>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </motion.div>

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
          <div style={{ fontSize: 10, fontWeight: 700, opacity: 0.65 }}>ПРИМЕР SCORE</div>
          <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: -1, lineHeight: 1 }}>
            86/100
          </div>
        </div>
      </Float>

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
            maxWidth: 240,
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
              fontSize: 13,
              flexShrink: 0,
            }}
          >
            1
          </span>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>Следующий шаг</div>
            <div style={{ fontSize: 11, color: "var(--muted)" }}>Проверить письмо перед отправкой</div>
          </div>
        </div>
      </Float>
    </div>
  );
}
