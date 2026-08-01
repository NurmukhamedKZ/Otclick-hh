"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Btn, Card, EmptyState, Skeleton, Tag, TextInput } from "@/components/otclick/ui";
import { IDoc } from "@/components/otclick/icons";
import { pushToast } from "@/components/toaster";

export type QAItem = {
  id: string;
  question: string;
  answer: string;
  source: string;
  vacancy_id: string | null;
  updated_at: string;
};

/** Q&A the user confirmed — reused in every AI prompt (forms, recruiter chats). */
export function QAMemoryCard() {
  const [items, setItems] = useState<QAItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [a, setA] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch<QAItem[]>("/api/qa")
      .then(setItems)
      .catch((e) => {
        setItems([]);
        setErr(e instanceof Error ? e.message : "не удалось загрузить");
      });
  }, []);

  async function save(question: string, answer: string) {
    if (!question.trim() || !answer.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const saved = await apiFetch<QAItem>("/api/qa", {
        method: "POST",
        body: JSON.stringify({ question, answer }),
      });
      setItems((prev) => [
        saved,
        ...(prev ?? []).filter((i) => i.question !== saved.question),
      ]);
      return true;
    } catch (e) {
      setErr(e instanceof Error ? e.message : "не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setErr(null);
    try {
      await apiFetch(`/api/qa/${id}`, { method: "DELETE" });
      setItems((prev) => (prev ?? []).filter((i) => i.id !== id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "не удалось удалить");
    }
  }

  async function copyAll() {
    if (!items || items.length === 0) return;
    const text = items
      .map((i) => `Вопрос: ${i.question}\nОтвет: ${i.answer}`)
      .join("\n\n");
    await navigator.clipboard.writeText(text);
    pushToast({ kind: "success", title: "Скопировано", body: `${items.length} пар вопрос-ответ` });
  }

  return (
    <Card style={{ gridColumn: "1 / -1" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <div style={{ fontSize: 17, fontWeight: 700 }}>Вопросы и ответы</div>
        <Btn kind="ghost" size="sm" disabled={!items || items.length === 0} onClick={copyAll}>
          скопировать всё
        </Btn>
      </div>
      <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 18 }}>
        Здесь копятся ответы, которые ты правишь в тестах и формах. ИИ использует
        их как источник правды, когда заполняет формы и отвечает рекрутёрам.
      </p>

      {err && <p style={{ fontSize: 13, color: "var(--err)", marginBottom: 12 }}>{err}</p>}

      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "flex-end",
          flexWrap: "wrap",
          marginBottom: 18,
        }}
      >
        <div style={{ flex: "2 1 240px" }}>
          <TextInput
            label="вопрос"
            value={q}
            placeholder="Укажите желаемый доход"
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div style={{ flex: "2 1 240px" }}>
          <TextInput
            label="ответ"
            value={a}
            placeholder="250 000-300 000 руб на руки"
            onChange={(e) => setA(e.target.value)}
          />
        </div>
        <Btn
          kind="primary"
          size="sm"
          disabled={busy || !q.trim() || !a.trim()}
          style={{ marginBottom: 14 }}
          onClick={async () => {
            if (await save(q, a)) {
              setQ("");
              setA("");
            }
          }}
        >
          добавить
        </Btn>
      </div>

      {items === null ? (
        <Skeleton h={56} count={3} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<IDoc size={20} />}
          title="Пока пусто"
          description="Отредактируй ответ в форме перед отправкой - он появится здесь."
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((item) => (
            <QARow key={item.id} item={item} onSave={save} onDelete={remove} />
          ))}
        </div>
      )}
    </Card>
  );
}

function QARow({
  item,
  onSave,
  onDelete,
}: {
  item: QAItem;
  onSave: (q: string, a: string) => Promise<boolean | undefined>;
  onDelete: (id: string) => void;
}) {
  const [answer, setAnswer] = useState(item.answer);
  const dirty = answer.trim() !== item.answer;

  return (
    <div
      style={{
        padding: "14px 16px",
        borderRadius: 14,
        background: "var(--bg-deep)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ fontSize: 14, fontWeight: 600, flex: 1, minWidth: 200 }}>
          {item.question}
        </div>
        <Tag tone="neutral">{item.source === "form" ? "из формы" : "вручную"}</Tag>
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <TextInput
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            style={{ marginBottom: 0 }}
          />
        </div>
        {dirty && (
          <Btn
            kind="yellow"
            size="sm"
            style={{ marginBottom: 14 }}
            onClick={() => onSave(item.question, answer)}
          >
            сохранить
          </Btn>
        )}
        <Btn
          kind="ghost"
          size="sm"
          style={{ marginBottom: 14 }}
          onClick={() => onDelete(item.id)}
        >
          удалить
        </Btn>
      </div>
    </div>
  );
}
