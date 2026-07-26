"use client";

import { useState } from "react";
import Link from "next/link";
import { Btn, Card, KeyHint, PageHeader } from "@/components/otclick/ui";
import { ISearch } from "@/components/otclick/icons";
import { openCommandPalette } from "@/components/otclick/command-palette";
import { useRecruiter, type Draft } from "@/hooks/useRecruiter";
import { useFormDrafts, type FormAnswer, type FormDraft } from "@/hooks/useFormDrafts";

function FormDraftCard({
  draft,
  onApprove,
  onDiscard,
}: {
  draft: FormDraft;
  onApprove: (id: string, answers: FormAnswer[], letter: string) => void;
  onDiscard: (id: string) => void;
}) {
  const [answers, setAnswers] = useState<FormAnswer[]>(draft.answers);
  const [letter, setLetter] = useState(draft.letter ?? "");

  const update = (idx: number, patch: Partial<FormAnswer>) =>
    setAnswers((prev) => prev.map((a, i) => (i === idx ? { ...a, ...patch } : a)));

  return (
    <Card style={{ display: "grid", gap: 10, gridTemplateColumns: "minmax(0, 1fr)" }}>
      <div style={{ fontWeight: 600, overflowWrap: "anywhere" }}>
        {draft.vacancy_title ?? `Вакансия ${draft.vacancy_id}`}
      </div>
      {draft.employer_name && (
        <div style={{ fontSize: 13, color: "var(--muted)", overflowWrap: "anywhere" }}>
          {draft.employer_name}
        </div>
      )}
      {draft.vacancy_url && (
        <a
          href={draft.vacancy_url}
          target="_blank"
          rel="noreferrer"
          style={{ fontSize: 13, color: "var(--coral)", textDecoration: "underline" }}
        >
          Открыть вакансию ↗
        </a>
      )}
      <div style={{ display: "grid", gap: 12, paddingTop: 6 }}>
        {answers.map((a, i) => (
          <div key={a.task_id} style={{ display: "grid", gap: 6, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, overflowWrap: "anywhere" }}>{a.question}</div>
            {a.type === "choice" && a.options ? (
              <select
                value={a.answer_id ?? ""}
                onChange={(e) => {
                  const id = e.target.value;
                  const text = a.options!.find((o) => o.id === id)?.text ?? "";
                  update(i, { answer_id: id, answer: text });
                }}
                style={{
                  width: "100%",
                  minWidth: 0,
                  padding: 8,
                  borderRadius: 10,
                  border: "1px solid var(--line)",
                  background: "var(--bg-deep)",
                  color: "var(--ink)",
                }}
              >
                {a.options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.text}
                  </option>
                ))}
              </select>
            ) : (
              <textarea
                value={a.answer}
                onChange={(e) => update(i, { answer: e.target.value })}
                rows={3}
                style={{
                  width: "100%",
                  resize: "vertical",
                  padding: 8,
                  borderRadius: 10,
                  border: "1px solid var(--line)",
                  background: "var(--bg-deep)",
                  color: "var(--ink)",
                  fontSize: 13,
                }}
              />
            )}
          </div>
        ))}
      </div>
      <div style={{ display: "grid", gap: 6, paddingTop: 6 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>Сопроводительное (опционально)</div>
        <textarea
          value={letter}
          onChange={(e) => setLetter(e.target.value)}
          rows={3}
          style={{
            width: "100%",
            resize: "vertical",
            padding: 8,
            borderRadius: 10,
            border: "1px solid var(--line)",
            background: "var(--bg-deep)",
            color: "var(--ink)",
            fontSize: 13,
          }}
        />
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Btn kind="primary" size="sm" onClick={() => onApprove(draft.id, answers, letter)}>
          Подтвердить и отправить
        </Btn>
        <Btn kind="ghost" size="sm" onClick={() => onDiscard(draft.id)}>
          Отклонить
        </Btn>
      </div>
    </Card>
  );
}

function DraftCard({
  draft,
  onSend,
  onDiscard,
}: {
  draft: Draft;
  onSend: (id: string, msg: string) => void;
  onDiscard: (id: string) => void;
}) {
  const [text, setText] = useState(draft.draft_text);
  const [editing, setEditing] = useState(false);
  const [buf, setBuf] = useState(draft.draft_text);
  return (
    <Card style={{ display: "grid", gap: 10, gridTemplateColumns: "minmax(0, 1fr)" }}>
      {draft.question_text && (
        <div
          style={{
            background: "var(--bg-deep)",
            borderLeft: "3px solid var(--coral)",
            borderRadius: 10,
            padding: "10px 12px",
            display: "grid",
            gap: 4,
          }}
        >
          <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 600, letterSpacing: 0.4, textTransform: "uppercase" }}>
            Вопрос рекрутёра
          </div>
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.45,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: "var(--ink)",
            }}
          >
            {draft.question_text}
          </div>
        </div>
      )}
      {draft.reason && (
        <div style={{ fontSize: 13, color: "var(--muted)" }}>Причина: {draft.reason}</div>
      )}
      <div
        style={{
          background: "var(--bg-deep)",
          borderLeft: "3px solid var(--ink)",
          borderRadius: 10,
          padding: "10px 12px",
          display: "grid",
          gap: 6,
        }}
      >
        <div
          style={{
            fontSize: 11,
            color: "var(--muted)",
            fontWeight: 600,
            letterSpacing: 0.4,
            textTransform: "uppercase",
          }}
        >
          Ответ ИИ
        </div>
        {editing ? (
          <textarea
            value={buf}
            onChange={(e) => setBuf(e.target.value)}
            rows={4}
            autoFocus
            style={{
              width: "100%",
              resize: "vertical",
              padding: 8,
              borderRadius: 8,
              border: "1px solid var(--line)",
              background: "var(--surface)",
              color: "var(--ink)",
              fontSize: 14,
              lineHeight: 1.45,
              fontFamily: "inherit",
            }}
          />
        ) : (
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.45,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: "var(--ink)",
            }}
          >
            {text}
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {editing ? (
          <>
            <Btn
              kind="primary"
              size="sm"
              onClick={() => {
                setText(buf);
                setEditing(false);
              }}
            >
              Сохранить
            </Btn>
            <Btn
              kind="ghost"
              size="sm"
              onClick={() => {
                setBuf(text);
                setEditing(false);
              }}
            >
              Отмена
            </Btn>
          </>
        ) : (
          <>
            <Btn kind="primary" size="sm" onClick={() => onSend(draft.id, text)}>
              Отправить
            </Btn>
            <Btn
              kind="ghost"
              size="sm"
              onClick={() => {
                setBuf(text);
                setEditing(true);
              }}
            >
              Редактировать
            </Btn>
            <Btn kind="ghost" size="sm" onClick={() => onDiscard(draft.id)}>
              Отклонить
            </Btn>
          </>
        )}
        <Link
          href={`/chats?n=${encodeURIComponent(draft.negotiation_id)}`}
          style={{ marginLeft: "auto" }}
        >
          <Btn kind="soft" size="sm">
            Перейти к чату ↗
          </Btn>
        </Link>
      </div>
    </Card>
  );
}

export default function RecruiterPage() {
  const { drafts, todos, loading, error, sendDraft, discardDraft, resolveTodo } = useRecruiter();
  const {
    drafts: formDrafts,
    loading: formLoading,
    error: formError,
    approve: approveForm,
    discard: discardForm,
  } = useFormDrafts();

  return (
    <>
      <PageHeader title="Todo" subtitle="что ждёт твоего решения" crumbs={[{ label: "Главная", href: "/dashboard" }, { label: "Todo" }]}
        actions={<Btn kind="ghost" size="sm" icon={<ISearch size={15} />} onClick={openCommandPalette}>поиск <KeyHint>⌘K</KeyHint></Btn>}
      />
      {error && <div style={{ color: "var(--err)", padding: 16 }}>{error}</div>}
      {formError && <div style={{ color: "var(--err)", padding: 16 }}>{formError}</div>}
      {loading || formLoading ? (
        <div style={{ padding: 16, color: "var(--muted)" }}>Загрузка…</div>
      ) : (
        <div style={{ display: "grid", gap: 28, padding: 16, gridTemplateColumns: "minmax(0, 1fr)" }}>
          <section style={{ display: "grid", gap: 12, minWidth: 0, gridTemplateColumns: "minmax(0, 1fr)" }}>
            <h2 style={{ fontSize: 16, fontWeight: 700 }}>
              Тесты вакансий на аппрув ({formDrafts.length})
            </h2>
            {formDrafts.length === 0 && (
              <div style={{ fontSize: 14, color: "var(--muted)" }}>
                Нет тестов на проверку.
              </div>
            )}
            {formDrafts.map((f) => (
              <FormDraftCard
                key={f.id}
                draft={f}
                onApprove={approveForm}
                onDiscard={discardForm}
              />
            ))}
          </section>

          <section style={{ display: "grid", gap: 12, minWidth: 0, gridTemplateColumns: "minmax(0, 1fr)" }}>
            <h2 style={{ fontSize: 16, fontWeight: 700 }}>Черновики ответов ({drafts.length})</h2>
            {drafts.length === 0 && (
              <div style={{ fontSize: 14, color: "var(--muted)" }}>Нет черновиков.</div>
            )}
            {drafts.map((d) => (
              <DraftCard key={d.id} draft={d} onSend={sendDraft} onDiscard={discardDraft} />
            ))}
          </section>

          <section style={{ display: "grid", gap: 12, minWidth: 0, gridTemplateColumns: "minmax(0, 1fr)" }}>
            <h2 style={{ fontSize: 16, fontWeight: 700 }}>Задачи ({todos.length})</h2>
            {todos.length === 0 && (
              <div style={{ fontSize: 14, color: "var(--muted)" }}>Нет задач.</div>
            )}
            {todos.map((t) => (
              <Card key={t.id} style={{ display: "grid", gap: 6, gridTemplateColumns: "minmax(0, 1fr)" }}>
                <div style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{t.title}</div>
                {t.detail && <div style={{ fontSize: 14, overflowWrap: "anywhere" }}>{t.detail}</div>}
                {t.link && (
                  <a
                    href={t.link}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      fontSize: 14,
                      color: "var(--coral)",
                      textDecoration: "underline",
                      wordBreak: "break-all",
                      overflowWrap: "anywhere",
                    }}
                  >
                    {t.link}
                  </a>
                )}
                <div style={{ display: "flex", gap: 8, paddingTop: 4 }}>
                  <Btn kind="primary" size="sm" onClick={() => resolveTodo(t.id, "done")}>
                    Готово
                  </Btn>
                  <Btn kind="ghost" size="sm" onClick={() => resolveTodo(t.id, "dismiss")}>
                    Скрыть
                  </Btn>
                </div>
              </Card>
            ))}
          </section>
        </div>
      )}
    </>
  );
}
