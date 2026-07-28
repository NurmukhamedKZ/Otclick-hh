"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { createClient } from "@/lib/supabase/client";
import { apiFetch } from "@/lib/api";
import { matchCommands, type Command, type CommandGroup } from "@/lib/command-registry";
import { openFiltersDrawer } from "@/components/filters-drawer";
import { openNotificationsDrawer } from "@/components/notifications-drawer";
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
  const dialogRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
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
      // capture the trigger only on a real open, so re-firing while already open
      // cannot overwrite it with a node inside the palette itself
      setOpen((prev) => {
        if (!prev) triggerRef.current = document.activeElement;
        return true;
      });
    }
    function onKey(e: KeyboardEvent) {
      // e.code, not e.key: under a Cyrillic layout the K key reports "л"
      if (e.code === "KeyK" && (e.metaKey || e.ctrlKey)) {
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

  // the page behind must not scroll while the dialog is up
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

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
      ["/todo", "Задания", "задачи черновики анкеты todo"],
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
      { id: "act:notifications", label: "Открыть уведомления", group: "Действия", keywords: "события bell", run: openNotificationsDrawer },
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

  // keep the arrow-selected row visible in the scrollable list
  useEffect(() => {
    if (!open) return;
    listRef.current
      ?.querySelector<HTMLElement>('[aria-selected="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [cursor, open]);

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
    else if (e.key === "Tab") {
      // focus trap: aria-modal only tells assistive tech the rest is unavailable,
      // it does not stop Tab from walking into the page behind the backdrop
      const nodes = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'input, button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  let flat = -1;

  return (
    <div
      className="oc-palette-backdrop"
      onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}
    >
      <div
        ref={dialogRef}
        className="oc-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Командная палитра"
        onKeyDown={onKeyDown}
      >
        <input
          ref={inputRef}
          className="oc-palette__input"
          placeholder="куда пойдём или что сделаем?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Поиск команды"
          role="combobox"
          aria-expanded
          aria-controls="oc-palette-list"
          aria-activedescendant={results[cursor] ? `oc-cmd-${results[cursor].id}` : undefined}
          autoComplete="off"
        />
        {results.length === 0 ? (
          <div className="oc-palette__empty">ничего не нашлось</div>
        ) : (
          <ul
            ref={listRef}
            id="oc-palette-list"
            className="oc-palette__list"
            role="listbox"
            aria-label="Команды"
          >
            {GROUP_ORDER.map((group) => {
              const inGroup = results.filter((c) => c.group === group);
              if (inGroup.length === 0) return null;
              return (
                <li key={group} role="presentation">
                  <div className="oc-palette__group">{group}</div>
                  <ul style={{ listStyle: "none", margin: 0, padding: 0 }} role="group" aria-label={group}>
                    {inGroup.map((c) => {
                      flat += 1;
                      const i = flat;
                      return (
                        // role=option, not a button: aria-selected is only valid here,
                        // and list rows must stay out of the tab order (arrows drive them)
                        <li
                          key={c.id}
                          id={`oc-cmd-${c.id}`}
                          role="option"
                          aria-selected={i === cursor}
                          className="oc-palette__item"
                          onMouseEnter={() => setCursor(i)}
                          onClick={() => runAt(i)}
                        >
                          {c.label}
                          {c.hint && <span className="oc-palette__hint">{c.hint}</span>}
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
