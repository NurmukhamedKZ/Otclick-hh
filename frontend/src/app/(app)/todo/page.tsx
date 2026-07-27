"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Btn, Card, EmptyState, PageHeader, SegmentedTabs, Skeleton } from "@/components/otclick/ui";
import { ICheck, IDoc, IMail } from "@/components/otclick/icons";
import { useRecruiter, type Draft, type Todo } from "@/hooks/useRecruiter";
import { useFormDrafts, type FormAnswer, type FormDraft } from "@/hooks/useFormDrafts";
import { useChats, useChatMessages, type ChatSummary } from "@/hooks/useChats";

const SECTIONS = [
  { id: "forms", label: "Анкеты" },
  { id: "drafts", label: "Черновики" },
  { id: "tasks", label: "Задачи" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

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

function VacancyMeta({ meta }: { meta?: ChatSummary }) {
  if (!meta || (!meta.vacancy_name && !meta.employer_name)) return null;
  const href = meta.vacancy_id ? `https://hh.ru/vacancy/${meta.vacancy_id}` : null;
  return (
    <div style={{ display: "grid", gap: 2, minWidth: 0 }}>
      {meta.vacancy_name && (
        href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            style={{ fontWeight: 600, overflowWrap: "anywhere", color: "var(--ink)", textDecoration: "none" }}
          >
            {meta.vacancy_name}
          </a>
        ) : (
          <div style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{meta.vacancy_name}</div>
        )
      )}
      {meta.employer_name && (
        href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            style={{ fontSize: 13, color: "var(--muted)", overflowWrap: "anywhere", textDecoration: "none" }}
          >
            {meta.employer_name}
          </a>
        ) : (
          <div style={{ fontSize: 13, color: "var(--muted)", overflowWrap: "anywhere" }}>
            {meta.employer_name}
          </div>
        )
      )}
    </div>
  );
}

function ChatHistory({ negotiationId, vacancyId }: { negotiationId: string; vacancyId: string | null }) {
  const { messages, loading, error } = useChatMessages(negotiationId, vacancyId);

  if (loading && !messages) return <Skeleton h={16} count={3} />;
  if (error) return null;
  if (!messages || messages.length === 0) return null;

  return (
    <div
      style={{
        display: "grid",
        gap: 8,
        maxHeight: 260,
        overflowY: "auto",
        padding: "10px 12px",
        borderRadius: 10,
        background: "var(--bg-deep)",
        border: "1px solid var(--line)",
      }}
    >
      <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 600, letterSpacing: 0.4, textTransform: "uppercase" }}>
        История переписки
      </div>
      {messages.map((m) => (
        <div
          key={m.id}
          style={{
            justifySelf: m.from_employer ? "start" : "end",
            maxWidth: "85%",
            display: "grid",
            gap: 2,
          }}
        >
          <div
            style={{
              fontSize: 13,
              lineHeight: 1.4,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              padding: "6px 10px",
              borderRadius: 10,
              background: m.from_employer ? "var(--surface)" : "var(--ink)",
              color: m.from_employer ? "var(--ink)" : "#F5F1E6",
            }}
          >
            {m.text}
          </div>
        </div>
      ))}
    </div>
  );
}

function DraftCard({
  draft,
  meta,
  onSend,
  onDiscard,
}: {
  draft: Draft;
  meta?: ChatSummary;
  onSend: (id: string, msg: string) => void;
  onDiscard: (id: string) => void;
}) {
  const [text, setText] = useState(draft.draft_text);
  const [editing, setEditing] = useState(false);
  const [buf, setBuf] = useState(draft.draft_text);
  return (
    <Card style={{ display: "grid", gap: 10, gridTemplateColumns: "minmax(0, 1fr)" }}>
      <VacancyMeta meta={meta} />
      <ChatHistory negotiationId={draft.negotiation_id} vacancyId={meta?.vacancy_id ?? null} />
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

function FormsSection({
  formDrafts,
  approveForm,
  discardForm,
}: {
  formDrafts: FormDraft[];
  approveForm: (id: string, answers: FormAnswer[], letter: string) => void;
  discardForm: (id: string) => void;
}) {
  return (
    <div style={{ display: "grid", gap: 12, minWidth: 0, gridTemplateColumns: "minmax(0, 1fr)" }}>
      {formDrafts.length === 0 && (
        <EmptyState icon={<IDoc size={22} />} title="Анкет нет" description="Когда вакансия попросит пройти тест, ИИ заполнит его и покажет здесь на проверку." />
      )}
      {formDrafts.map((f) => (
        <FormDraftCard key={f.id} draft={f} onApprove={approveForm} onDiscard={discardForm} />
      ))}
    </div>
  );
}

function DraftsSection({
  drafts,
  sendDraft,
  discardDraft,
}: {
  drafts: Draft[];
  sendDraft: (id: string, msg: string) => void;
  discardDraft: (id: string) => void;
}) {
  // Reuses the /api/chats list (already fetched for the Chats page) purely for
  // its vacancy_name/employer_name — same data the Анкеты tab already shows.
  const { chats } = useChats(false);
  const metaById = useMemo(() => {
    const map = new Map<string, ChatSummary>();
    for (const c of chats ?? []) map.set(c.id, c);
    return map;
  }, [chats]);

  return (
    <div style={{ display: "grid", gap: 12, minWidth: 0, gridTemplateColumns: "minmax(0, 1fr)" }}>
      {drafts.length === 0 && (
        <EmptyState icon={<IMail size={22} />} title="Черновиков нет" description="Если ИИ не уверен в ответе рекрутёру, черновик появится здесь." action={{ label: "Открыть чаты", href: "/chats" }} />
      )}
      {drafts.map((d) => (
        <DraftCard
          key={d.id}
          draft={d}
          meta={metaById.get(d.negotiation_id)}
          onSend={sendDraft}
          onDiscard={discardDraft}
        />
      ))}
    </div>
  );
}

function TasksSection({
  todos,
  resolveTodo,
}: {
  todos: Todo[];
  resolveTodo: (id: string, action: "done" | "dismiss") => void;
}) {
  const { chats } = useChats(false);
  const metaById = useMemo(() => {
    const map = new Map<string, ChatSummary>();
    for (const c of chats ?? []) map.set(c.id, c);
    return map;
  }, [chats]);

  return (
    <div style={{ display: "grid", gap: 12, minWidth: 0, gridTemplateColumns: "minmax(0, 1fr)" }}>
      {todos.length === 0 && (
        <EmptyState icon={<ICheck size={22} />} title="Задач нет" description="ИИ-агент создаёт задачи, когда рекрутёр просит что-то сделать вне переписки." />
      )}
      {todos.map((t) => (
        <Card key={t.id} style={{ display: "grid", gap: 6, gridTemplateColumns: "minmax(0, 1fr)" }}>
          <VacancyMeta meta={metaById.get(t.negotiation_id)} />
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
    </div>
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

  const [active, setActive] = useState<SectionId>("forms");

  const counts: Record<SectionId, number> = {
    forms: formDrafts.length,
    drafts: drafts.length,
    tasks: todos.length,
  };

  return (
    <>
      <PageHeader title="Todo" subtitle="что ждёт твоего решения" crumbs={[{ label: "Главная", href: "/dashboard" }, { label: "Todo" }]} />
      <div style={{ padding: "0 16px" }}>
        <SegmentedTabs
          label="Разделы Todo"
          items={SECTIONS.map((s) => ({ id: s.id, label: s.label, count: counts[s.id] }))}
          value={active}
          onChange={(id) => setActive(id as SectionId)}
        />
      </div>
      {error && <div style={{ color: "var(--err)", padding: 16 }}>{error}</div>}
      {formError && <div style={{ color: "var(--err)", padding: 16 }}>{formError}</div>}
      {loading || formLoading ? (
        <Skeleton h={120} count={3} />
      ) : (
        <div style={{ padding: 16 }}>
          {active === "forms" && (
            <FormsSection formDrafts={formDrafts} approveForm={approveForm} discardForm={discardForm} />
          )}
          {active === "drafts" && (
            <DraftsSection drafts={drafts} sendDraft={sendDraft} discardDraft={discardDraft} />
          )}
          {active === "tasks" && <TasksSection todos={todos} resolveTodo={resolveTodo} />}
        </div>
      )}
    </>
  );
}
