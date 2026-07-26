"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Btn, Card, KeyHint, PageHeader, Tag, Toggle, type TagTone } from "@/components/otclick/ui";
import { openCommandPalette } from "@/components/otclick/command-palette";
import { IRefresh, ISearch } from "@/components/otclick/icons";
import {
  useChats,
  useChatMessages,
  type ChatMessage,
  type ChatSummary,
} from "@/hooks/useChats";

const STATE_TAG: Record<string, { tone: TagTone; label: string }> = {
  response: { tone: "ok", label: "Отклик отправлен" },
  invitation: { tone: "yellow", label: "Приглашение" },
  interview: { tone: "ok", label: "Собеседование" },
  offer: { tone: "ok", label: "Оффер" },
  discard: { tone: "err", label: "Отказ" },
  discard_by_applicant: { tone: "neutral", label: "Отозван" },
  discard_after_interview: { tone: "err", label: "Отказ" },
  hidden: { tone: "neutral", label: "Скрыт" },
  archive: { tone: "neutral", label: "Архив" },
};

function stateTag(state_id: string | null, state_name: string | null) {
  if (!state_id) return null;
  const meta = STATE_TAG[state_id] ?? { tone: "neutral" as TagTone, label: state_name ?? state_id };
  return (
    <Tag tone={meta.tone} style={{ fontSize: 11, padding: "3px 8px" }}>
      {meta.label}
    </Tag>
  );
}

function timeLabel(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate();
  if (sameDay) {
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || name[0].toUpperCase();
}

function Avatar({ name, logo }: { name: string | null; logo: string | null }) {
  if (logo) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={logo}
        alt={name ?? ""}
        style={{
          width: 44,
          height: 44,
          borderRadius: 14,
          objectFit: "cover",
          flexShrink: 0,
          background: "var(--bg-deep)",
        }}
      />
    );
  }
  return (
    <div
      style={{
        width: 44,
        height: 44,
        borderRadius: 14,
        background: "var(--bg-deep)",
        color: "var(--ink)",
        display: "grid",
        placeItems: "center",
        fontSize: 13,
        fontWeight: 700,
        flexShrink: 0,
      }}
    >
      {initials(name)}
    </div>
  );
}

function ChatRow({
  chat,
  active,
  onClick,
}: {
  chat: ChatSummary;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: "100%",
        textAlign: "left",
        padding: 12,
        borderRadius: 16,
        border: "none",
        background: active ? "var(--ink)" : "transparent",
        color: active ? "#F5F1E6" : "var(--ink)",
        cursor: "pointer",
        display: "flex",
        gap: 12,
        alignItems: "flex-start",
        transition: "background .15s",
      }}
    >
      <Avatar name={chat.employer_name} logo={chat.employer_logo} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 8,
            alignItems: "baseline",
          }}
        >
          <div
            style={{
              fontWeight: 700,
              fontSize: 14,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              flex: 1,
            }}
          >
            {chat.vacancy_name ?? "Без названия"}
          </div>
          <div
            style={{
              fontSize: 12,
              opacity: 0.7,
              flexShrink: 0,
            }}
          >
            {timeLabel(chat.updated_at)}
          </div>
        </div>
        <div
          style={{
            fontSize: 13,
            opacity: 0.75,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            marginTop: 2,
          }}
        >
          {chat.employer_name ?? ""}
        </div>
        <div
          style={{
            display: "flex",
            gap: 6,
            alignItems: "center",
            marginTop: 6,
          }}
        >
          {stateTag(chat.state_id, chat.state_name)}
          {chat.has_updates && (
            <span
              title="Новые сообщения"
              style={{
                background: "var(--coral)",
                color: "#fff",
                fontSize: 11,
                fontWeight: 700,
                padding: "2px 7px",
                borderRadius: 999,
                minWidth: 18,
                textAlign: "center",
              }}
            >
              {chat.unread > 0 ? chat.unread : "•"}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (same(d, today)) return "Сегодня";
  if (same(d, yesterday)) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

function MessageBubble({ m }: { m: ChatMessage }) {
  const fromEmp = m.from_employer;
  const isResponse = m.kind === "response";
  const hasText = m.text.trim().length > 0;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: fromEmp ? "flex-start" : "flex-end",
      }}
    >
      <div
        style={{
          maxWidth: "70%",
          background: fromEmp ? "var(--surface)" : "var(--ink)",
          color: fromEmp ? "var(--ink)" : "#F5F1E6",
          padding: "10px 14px",
          borderRadius: 16,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontSize: 14,
          lineHeight: 1.45,
        }}
      >
        {isResponse && (
          <div style={{ fontWeight: 700, marginBottom: hasText ? 6 : 0 }}>
            Отклик на вакансию
          </div>
        )}
        {hasText ? (
          m.text
        ) : isResponse ? (
          <div style={{ opacity: 0.75, fontStyle: "italic" }}>
            Без сопроводительного письма
          </div>
        ) : null}
        <div
          style={{
            fontSize: 11,
            opacity: 0.6,
            marginTop: 4,
            textAlign: "right",
          }}
        >
          {m.created_at ? timeLabel(m.created_at) : ""}
        </div>
      </div>
    </div>
  );
}

function MessagesPane({
  chat,
  onSent,
}: {
  chat: ChatSummary | null;
  onSent: () => void;
}) {
  const { messages, loading, error, send, refresh } = useChatMessages(
    chat?.id ?? null,
    chat?.vacancy_id ?? null,
  );
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const READONLY_STATES = new Set([
    "discard",
    "discard_by_employer",
    "discard_after_interview",
    "discard_by_applicant",
    "discard_visited",
    "discard_no_appearance",
    "hidden",
    "archive",
    "discard_to_other_vacancy",
  ]);
  const canSend = !!chat && !READONLY_STATES.has(chat.state_id ?? "");

  async function onSend() {
    const text = draft.trim();
    if (!text || !chat) return;
    setSending(true);
    try {
      await send(text);
      setDraft("");
      onSent();
    } catch (e) {
      alert(e instanceof Error ? e.message : "send failed");
    } finally {
      setSending(false);
    }
  }

  if (!chat) {
    return (
      <div
        style={{
          flex: 1,
          display: "grid",
          placeItems: "center",
          color: "var(--muted)",
          fontSize: 14,
        }}
      >
        Выберите чат слева
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
      <div
        style={{
          padding: "14px 22px",
          display: "flex",
          gap: 12,
          alignItems: "center",
          borderBottom: "1px solid var(--line)",
        }}
      >
        {chat.vacancy_id ? (
          <a
            href={`https://hh.ru/vacancy/${chat.vacancy_id}`}
            target="_blank"
            rel="noopener noreferrer"
            title="Открыть вакансию на hh.ru"
            style={{ flexShrink: 0 }}
          >
            <Avatar name={chat.employer_name} logo={chat.employer_logo} />
          </a>
        ) : (
          <Avatar name={chat.employer_name} logo={chat.employer_logo} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          {chat.vacancy_id ? (
            <a
              href={`https://hh.ru/vacancy/${chat.vacancy_id}`}
              target="_blank"
              rel="noopener noreferrer"
              title="Открыть вакансию на hh.ru"
              style={{
                fontWeight: 700,
                fontSize: 15,
                color: "var(--ink)",
                textDecoration: "none",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.textDecoration = "underline")}
              onMouseLeave={(e) => (e.currentTarget.style.textDecoration = "none")}
            >
              {chat.vacancy_name ?? "Без названия"}
            </a>
          ) : (
            <div style={{ fontWeight: 700, fontSize: 15 }}>
              {chat.vacancy_name ?? "Без названия"}
            </div>
          )}
          <div style={{ fontSize: 13, color: "var(--muted)" }}>
            {chat.employer_name ?? ""}
          </div>
        </div>
        {stateTag(chat.state_id, chat.state_name)}
        <button
          type="button"
          onClick={() => refresh()}
          title="Обновить"
          style={{
            background: "transparent",
            border: "1px solid var(--line)",
            borderRadius: 999,
            width: 34,
            height: 34,
            display: "grid",
            placeItems: "center",
            cursor: "pointer",
            color: "var(--ink)",
          }}
        >
          <IRefresh size={16} />
        </button>
      </div>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: 22,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          background: "var(--bg-deep)",
        }}
      >
        {loading && !messages && (
          <div style={{ color: "var(--muted)", textAlign: "center", fontSize: 13 }}>
            Загрузка…
          </div>
        )}
        {error && (
          <div style={{ color: "var(--err)", textAlign: "center", fontSize: 13 }}>
            {error}
          </div>
        )}
        {messages?.length === 0 && !loading && (
          <div style={{ color: "var(--muted)", textAlign: "center", fontSize: 13 }}>
            Сообщений нет
          </div>
        )}
        {messages?.map((m, i) => {
          const prev = i > 0 ? messages[i - 1] : null;
          const dayChanged =
            m.created_at &&
            (!prev?.created_at ||
              new Date(m.created_at).toDateString() !==
                new Date(prev.created_at).toDateString());
          return (
            <div key={m.id} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {dayChanged && m.created_at && (
                <div
                  style={{
                    textAlign: "center",
                    color: "var(--muted)",
                    fontSize: 12,
                    margin: "8px 0",
                  }}
                >
                  {dayLabel(m.created_at)}
                </div>
              )}
              <MessageBubble m={m} />
            </div>
          );
        })}
      </div>

      <div
        style={{
          padding: 16,
          borderTop: "1px solid var(--line)",
          background: "var(--surface)",
        }}
      >
        {canSend ? (
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Сообщение работодателю…"
              rows={2}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  onSend();
                }
              }}
              style={{
                flex: 1,
                resize: "vertical",
                padding: 12,
                borderRadius: 14,
                border: "1px solid var(--line)",
                background: "var(--bg-deep)",
                color: "var(--ink)",
                fontSize: 14,
                lineHeight: 1.4,
                fontFamily: "inherit",
              }}
            />
            <Btn kind="primary" onClick={onSend} disabled={sending || !draft.trim()}>
              {sending ? "…" : "Отправить"}
            </Btn>
          </div>
        ) : (
          <div
            style={{
              textAlign: "center",
              color: "var(--muted)",
              fontSize: 13,
              padding: "8px 0",
            }}
          >
            Переписка будет доступна после приглашения работодателя
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatsPage() {
  const searchParams = useSearchParams();
  const deepLinkId = searchParams.get("n");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { chats, found, error, loading, refresh } = useChats(unreadOnly);

  const filtered = useMemo(() => {
    if (!chats) return null;
    const q = search.trim().toLowerCase();
    if (!q) return chats;
    return chats.filter(
      (c) =>
        (c.vacancy_name ?? "").toLowerCase().includes(q) ||
        (c.employer_name ?? "").toLowerCase().includes(q),
    );
  }, [chats, search]);

  useEffect(() => {
    if (deepLinkId && chats) {
      // honor ?n=… deep link from /todo. Falls back to first chat if id is
      // not in the loaded page (chat older than 50 items — rare).
      const hit = chats.find((c) => c.id === deepLinkId);
      if (hit) {
        setSelectedId(hit.id);
        return;
      }
    }
    if (!selectedId && filtered && filtered.length > 0) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId, deepLinkId, chats]);

  const fromList =
    chats?.find((c) => c.id === (deepLinkId ?? selectedId)) ?? null;
  // Deep-link target may live past page 1 — render messages with a stub so the
  // chat is reachable even when the summary row isn't in the current list.
  const stubForDeepLink: ChatSummary | null =
    deepLinkId && !fromList
      ? {
          id: deepLinkId,
          vacancy_id: null,
          vacancy_name: null,
          employer_name: null,
          employer_logo: null,
          state_id: null,
          state_name: null,
          updated_at: null,
          unread: 0,
          has_updates: false,
        }
      : null;
  const selected = fromList ?? stubForDeepLink;

  const chatName = selected?.employer_name;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <PageHeader title="Чаты" subtitle="переписка с работодателями" crumbs={[{ label: "Главная", href: "/dashboard" }, { label: "Чаты" }, ...(chatName ? [{ label: chatName }] : [])]}
        actions={<Btn kind="ghost" size="sm" icon={<ISearch size={15} />} onClick={openCommandPalette}>поиск <KeyHint>⌘K</KeyHint></Btn>}
      />
      <Card
        className="oc-chat-card"
        style={{
          padding: 0,
          overflow: "hidden",
          display: "flex",
          height: "calc(100vh - 160px)",
          minHeight: 540,
        }}
      >
        <aside
          className="oc-chat-aside"
          style={{
            width: 360,
            flexShrink: 0,
            borderRight: "1px solid var(--line)",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}
        >
          <div
            style={{
              padding: 16,
              borderBottom: "1px solid var(--line)",
              display: "grid",
              gap: 10,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800 }}>Мои чаты</h2>
                <span
                  style={{
                    background: "var(--bg-deep)",
                    padding: "2px 10px",
                    borderRadius: 999,
                    fontSize: 13,
                    fontWeight: 600,
                    color: "var(--muted)",
                  }}
                >
                  {found}
                </span>
              </div>
              <button
                type="button"
                onClick={() => refresh()}
                title="Обновить"
                style={{
                  background: "transparent",
                  border: "1px solid var(--line)",
                  borderRadius: 999,
                  width: 32,
                  height: 32,
                  display: "grid",
                  placeItems: "center",
                  cursor: "pointer",
                  color: "var(--ink)",
                }}
              >
                <IRefresh size={15} />
              </button>
            </div>
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                background: "var(--bg-deep)",
                borderRadius: 12,
                padding: "8px 12px",
              }}
            >
              <ISearch size={15} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Поиск"
                style={{
                  flex: 1,
                  border: "none",
                  background: "transparent",
                  outline: "none",
                  fontSize: 14,
                  color: "var(--ink)",
                }}
              />
            </div>
            <label
              style={{
                display: "flex",
                gap: 10,
                alignItems: "center",
                fontSize: 13,
                color: "var(--ink)",
                cursor: "pointer",
              }}
            >
              <span style={{ flex: 1 }}>Только непрочитанные</span>
              <Toggle on={unreadOnly} onChange={setUnreadOnly} />
            </label>
          </div>

          <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
            {loading && !chats && (
              <div style={{ textAlign: "center", padding: 20, color: "var(--muted)" }}>
                Загрузка…
              </div>
            )}
            {error && (
              <div style={{ textAlign: "center", padding: 20, color: "var(--err)", fontSize: 13 }}>
                {error}
              </div>
            )}
            {filtered && filtered.length === 0 && !loading && (
              <div style={{ textAlign: "center", padding: 30, color: "var(--muted)", fontSize: 13 }}>
                Чатов нет
              </div>
            )}
            {filtered?.map((c) => (
              <ChatRow
                key={c.id}
                chat={c}
                active={c.id === selectedId}
                onClick={() => setSelectedId(c.id)}
              />
            ))}
          </div>
        </aside>

        <MessagesPane chat={selected} onSent={() => refresh()} />
      </Card>
    </div>
  );
}
