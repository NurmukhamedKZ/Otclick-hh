"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { createClient } from "@/lib/supabase/client";
import { apiFetch } from "@/lib/api";
import { matchCommands, type Command, type CommandGroup } from "@/lib/command-registry";
import { openFiltersDrawer } from "@/components/filters-drawer";
import { pushToast } from "@/components/toaster";
import type { Application } from "@/lib/types";

const EVENT = "oc:open-command-palette";

export function openCommandPalette() {
  window.dispatchEvent(new CustomEvent(EVENT));
}

const GROUP_ORDER: CommandGroup[] = ["Навигация", "Действия", "Отклики"];

export default function CommandPalette() {
  const router = useRouter();
  const qc = useQueryClient();
  const supabase = useMemo(() => createClient(), []);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [recent, setRecent] = useState<Application[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<Element | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setCursor(0);
    if (triggerRef.current instanceof HTMLElement) triggerRef.current.focus();
  }, []);

  // open via the module-level opener or ⌘K / Ctrl+K
  useEffect(() => {
    function show() {
      triggerRef.current = document.activeElement;
      setOpen(true);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        show();
      }
    }
    window.addEventListener(EVENT, show);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener(EVENT, show);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    supabase
      .from("applications")
      .select("id,vacancy_id,employer_id,status,created_at")
      .order("created_at", { ascending: false })
      .limit(20)
      .then(({ data }) => setRecent((data ?? []) as Application[]));
  }, [open, supabase]);

  const commands: (Command & { run: () => void })[] = useMemo(() => {
    const nav = [
      ["/dashboard", "Главная", "дашборд обзор"],
      ["/applications", "Отклики", "заявки вакансии"],
      ["/chats", "Чаты", "переписка рекрутёр сообщения"],
      ["/todo", "Todo", "задачи черновики анкеты"],
      ["/notifications", "Уведомления", "события"],
      ["/account", "Аккаунт", "настройки профиль hh"],
      ["/billing", "Подписка", "оплата тариф pro billing"],
    ].map(([href, label, keywords]) => ({
      id: `nav:${href}`,
      label,
      group: "Навигация" as const,
      keywords,
      run: () => router.push(href),
    }));

    const post = (path: string, ok: string) => async () => {
      try {
        await apiFetch(path, { method: "POST" });
        qc.invalidateQueries({ queryKey: ["worker-status"] });
        pushToast({ kind: "success", title: ok });
      } catch (e) {
        pushToast({ kind: "error", title: e instanceof Error ? e.message : "не удалось" });
      }
    };

    const actions: (Command & { run: () => void })[] = [
      { id: "act:start", label: "Запустить автоотклик", group: "Действия", keywords: "старт worker run", run: post("/api/worker/start", "worker запущен") },
      { id: "act:stop", label: "Остановить автоотклик", group: "Действия", keywords: "стоп worker pause", run: post("/api/worker/stop", "worker остановлен") },
      { id: "act:agent-start", label: "Запустить ИИ-агента", group: "Действия", keywords: "агент ai старт", run: post("/api/worker/agent/start", "ИИ-агент запущен") },
      { id: "act:agent-stop", label: "Остановить ИИ-агента", group: "Действия", keywords: "агент ai стоп", run: post("/api/worker/agent/stop", "ИИ-агент остановлен") },
      { id: "act:filters", label: "Открыть фильтры", group: "Действия", keywords: "поиск настройки вакансий", run: openFiltersDrawer },
      { id: "act:sync", label: "Синхронизировать резюме", group: "Действия", keywords: "резюме hh обновить", run: post("/api/resumes/sync", "резюме синхронизированы") },
      { id: "act:refresh", label: "Обновить статус воркера", group: "Действия", keywords: "refresh статус", run: () => { qc.invalidateQueries({ queryKey: ["worker-status"] }); } },
      { id: "act:signout", label: "Выйти", group: "Действия", keywords: "logout выход", run: async () => { await supabase.auth.signOut(); router.push("/auth"); } },
    ];

    const apps = recent.map((a) => ({
      id: `app:${a.id}`,
      label: `vacancy ${a.vacancy_id}`,
      group: "Отклики" as const,
      keywords: `${a.employer_id ?? ""} ${a.status}`,
      hint: "открыть на hh.ru",
      run: () => window.open(`https://hh.ru/vacancy/${a.vacancy_id}`, "_blank", "noopener"),
    }));

    return [...nav, ...actions, ...apps];
  }, [router, qc, supabase, recent]);

  const results = useMemo(() => matchCommands(commands, query) as typeof commands, [commands, query]);

  useEffect(() => setCursor(0), [query]);

  if (!open) return null;

  function runAt(i: number) {
    const c = results[i];
    if (!c) return;
    close();
    c.run();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(results.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); runAt(cursor); }
  }

  let flat = -1;

  return (
    <div
      className="oc-palette-backdrop"
      onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}
    >
      <div className="oc-palette" role="dialog" aria-modal="true" aria-label="Командная палитра" onKeyDown={onKeyDown}>
        <input
          ref={inputRef}
          className="oc-palette__input"
          placeholder="куда пойдём или что сделаем?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Поиск команды"
        />
        {results.length === 0 ? (
          <div className="oc-palette__empty">ничего не нашлось</div>
        ) : (
          <ul className="oc-palette__list">
            {GROUP_ORDER.map((group) => {
              const inGroup = results.filter((c) => c.group === group);
              if (inGroup.length === 0) return null;
              return (
                <li key={group}>
                  <div className="oc-palette__group">{group}</div>
                  <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                    {inGroup.map((c) => {
                      flat += 1;
                      const i = flat;
                      return (
                        <li key={c.id}>
                          <button
                            type="button"
                            className="oc-palette__item"
                            aria-selected={i === cursor}
                            onMouseEnter={() => setCursor(i)}
                            onClick={() => runAt(i)}
                          >
                            {c.label}
                            {c.hint && <span className="oc-palette__hint">{c.hint}</span>}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
