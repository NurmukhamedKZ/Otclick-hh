"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { useFilters } from "@/hooks/useFilters";
import { openFiltersDrawer } from "@/components/filters-drawer";
import { pushToast } from "@/components/toaster";
import { Btn } from "@/components/otclick/ui";
import {
  ICheck,
  IClose,
  IDoc,
  IFilter,
  ILink,
  IPlay,
  ISpark,
  IHome,
  IList,
  IMail,
  IBell,
  IUser,
} from "@/components/otclick/icons";
import type { Resume, ResumesList, WorkerStatus } from "@/lib/types";

const PAGES = [
  { icon: <IHome size={15} />, name: "Главная", desc: "статус, лимиты, быстрые действия" },
  { icon: <IList size={15} />, name: "Отклики", desc: "все отправленные отклики и их статусы" },
  { icon: <IMail size={15} />, name: "Чаты", desc: "переписка с рекрутёрами, ИИ отвечает сам" },
  { icon: <IDoc size={15} />, name: "Задания", desc: "задачи от агента, что требует твоего внимания" },
  { icon: <IBell size={15} />, name: "Уведомления", desc: "события воркера в реальном времени" },
  { icon: <IUser size={15} />, name: "Аккаунт", desc: "подключение hh, подписка, настройки" },
];

type StepKey = "connect" | "resume" | "filter" | "launch";

type HHStatus = { connected: boolean };

function StepRow({
  index,
  done,
  active,
  icon,
  title,
  subtitle,
  children,
}: {
  index: number;
  done: boolean;
  active: boolean;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 14,
        padding: 16,
        borderRadius: 16,
        background: active ? "var(--bg-deep)" : "transparent",
        border: active ? "1px solid var(--line-2)" : "1px solid transparent",
        opacity: done || active ? 1 : 0.55,
        transition: "opacity .2s, background .2s",
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 11,
          flexShrink: 0,
          display: "grid",
          placeItems: "center",
          background: done ? "var(--ok)" : active ? "var(--ink)" : "var(--line-2)",
          color: done || active ? "#F5F1E6" : "var(--muted)",
          fontWeight: 700,
          fontSize: 14,
        }}
      >
        {done ? <ICheck size={16} /> : index}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {icon}
          <span style={{ fontSize: 15, fontWeight: 700 }}>{title}</span>
          {done && (
            <span style={{ fontSize: 12, color: "var(--ok)", fontWeight: 600 }}>готово</span>
          )}
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 3 }}>{subtitle}</div>
        {active && !done && children ? <div style={{ marginTop: 12 }}>{children}</div> : null}
      </div>
    </div>
  );
}

export default function OnboardingModal() {
  const qc = useQueryClient();
  const router = useRouter();
  const supabase = createClient();

  const [ready, setReady] = useState(false);
  const [show, setShow] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [finalSlide, setFinalSlide] = useState(false);

  // profile flag
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return;
      const { data } = await supabase
        .from("profiles")
        .select("onboarded")
        .eq("id", user.id)
        .single();
      if (cancelled) return;
      setShow(!data?.onboarded);
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [supabase]);

  // step state sources
  const { data: hh } = useQuery({
    queryKey: ["hh-status"],
    queryFn: () => apiFetch<HHStatus>("/api/hh/status"),
    enabled: show,
    refetchInterval: show ? 4000 : false,
  });

  const [resumes, setResumes] = useState<Resume[] | null>(null);
  const loadResumes = useCallback(async () => {
    try {
      const data = await apiFetch<ResumesList>("/api/resumes");
      setResumes(data.items);
    } catch {
      setResumes([]);
    }
  }, []);
  useEffect(() => {
    if (show) loadResumes();
  }, [show, loadResumes]);

  const { items: filters, reload: reloadFilters } = useFilters();

  const { data: worker } = useQuery({
    queryKey: ["worker-status"],
    queryFn: () => apiFetch<WorkerStatus>("/api/worker/status"),
    enabled: show,
    refetchInterval: show ? 4000 : false,
  });

  const connectDone = hh?.connected ?? false;
  const resumeDone = (resumes?.length ?? 0) > 0;
  const filterDone = (filters?.length ?? 0) > 0;
  const launchDone =
    worker?.state === "running" || worker?.agent_state === "running";

  // first not-done step is active
  const order: StepKey[] = ["connect", "resume", "filter", "launch"];
  const doneMap: Record<StepKey, boolean> = {
    connect: connectDone,
    resume: resumeDone,
    filter: filterDone,
    launch: launchDone,
  };
  const activeStep = order.find((k) => !doneMap[k]) ?? null;
  const allDone = connectDone && resumeDone && filterDone && launchDone;

  // actions
  const syncM = useMutation({
    mutationFn: () => apiFetch<ResumesList>("/api/resumes/sync", { method: "POST" }),
    onSuccess: (data) => {
      setResumes(data.items);
      if (data.items.length === 0) {
        pushToast({ kind: "info", title: "резюме на hh не найдены" });
      } else {
        pushToast({ kind: "success", title: "резюме синхронизированы" });
      }
    },
    onError: (e) =>
      pushToast({ kind: "error", title: e instanceof Error ? e.message : "ошибка синка" }),
  });

  const startWorkerM = useMutation({
    mutationFn: () => apiFetch("/api/worker/start", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker-status"] });
      pushToast({ kind: "success", title: "автоотклик запущен" });
    },
    onError: (e) =>
      pushToast({ kind: "error", title: e instanceof Error ? e.message : "ошибка запуска" }),
  });

  const startAgentM = useMutation({
    mutationFn: () => apiFetch("/api/worker/agent/start", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["worker-status"] });
      pushToast({ kind: "success", title: "ИИ-агент запущен" });
    },
    onError: (e) =>
      pushToast({ kind: "error", title: e instanceof Error ? e.message : "ошибка запуска" }),
  });

  const openFilters = () => {
    setMinimized(true);
    openFiltersDrawer();
  };
  const resume = () => {
    setMinimized(false);
    reloadFilters();
  };

  // while minimized for the filter step, poll filters; reopen once one exists
  useEffect(() => {
    if (!minimized) return;
    const id = setInterval(reloadFilters, 1500);
    return () => clearInterval(id);
  }, [minimized, reloadFilters]);
  useEffect(() => {
    if (minimized && filterDone) setMinimized(false);
  }, [minimized, filterDone]);

  const finish = async () => {
    setShow(false);
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (user) {
      await supabase.from("profiles").update({ onboarded: true }).eq("id", user.id);
    }
  };

  if (!ready || !show) return null;

  if (minimized) {
    return (
      <button
        type="button"
        onClick={resume}
        style={{
          position: "fixed",
          top: 20,
          left: 20,
          zIndex: 1200,
          border: "none",
          background: "var(--ink)",
          color: "#F5F1E6",
          borderRadius: 999,
          padding: "12px 18px",
          fontWeight: 600,
          fontSize: 14,
          cursor: "pointer",
          boxShadow: "0 8px 24px rgba(0,0,0,.25)",
        }}
      >
        Закончить настройку
      </button>
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1100,
        background: "rgba(20,16,10,.55)",
        backdropFilter: "blur(4px)",
        display: "grid",
        placeItems: "center",
        padding: 16,
      }}
    >
      <div
        style={{
          width: "min(560px, 100%)",
          maxHeight: "90vh",
          overflowY: "auto",
          background: "var(--surface)",
          borderRadius: 24,
          padding: 24,
          boxShadow: "0 24px 60px rgba(0,0,0,.35)",
        }}
      >
        {finalSlide ? (
          <>
            <div style={{ fontSize: 22, fontWeight: 800 }}>Всё готово 🎉</div>
            <div style={{ fontSize: 14, color: "var(--muted)", marginTop: 6, marginBottom: 18 }}>
              Коротко о разделах — куда смотреть дальше:
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {PAGES.map((p) => (
                <div
                  key={p.name}
                  style={{
                    display: "flex",
                    gap: 12,
                    alignItems: "center",
                    padding: "10px 12px",
                    background: "var(--bg-deep)",
                    borderRadius: 12,
                  }}
                >
                  <div
                    style={{
                      width: 30,
                      height: 30,
                      borderRadius: 9,
                      flexShrink: 0,
                      display: "grid",
                      placeItems: "center",
                      background: "var(--ink)",
                      color: "#F5F1E6",
                    }}
                  >
                    {p.icon}
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>{p.name}</div>
                    <div style={{ fontSize: 12, color: "var(--muted)" }}>{p.desc}</div>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 20 }}>
              <Btn kind="primary" onClick={finish} style={{ width: "100%" }}>
                Начать работу
              </Btn>
            </div>
          </>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 22, fontWeight: 800 }}>Настройка за 4 шага</div>
                <div style={{ fontSize: 14, color: "var(--muted)", marginTop: 6 }}>
                  Подключи hh и подготовь автоотклик.
                </div>
              </div>
              <button
                type="button"
                onClick={finish}
                title="пропустить"
                style={{
                  border: "none",
                  background: "var(--bg-deep)",
                  color: "var(--muted)",
                  borderRadius: 10,
                  width: 32,
                  height: 32,
                  display: "grid",
                  placeItems: "center",
                  cursor: "pointer",
                }}
              >
                <IClose size={16} />
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 18 }}>
              <StepRow
                index={1}
                done={connectDone}
                active={activeStep === "connect"}
                icon={<ILink size={15} />}
                title="Подключить hh"
                subtitle="войди в свой аккаунт hh — без него не получится откликаться"
              >
                <Btn kind="primary" size="sm" onClick={() => router.push("/onboarding")}>
                  Подключить hh
                </Btn>
              </StepRow>

              <StepRow
                index={2}
                done={resumeDone}
                active={activeStep === "resume"}
                icon={<IDoc size={15} />}
                title="Синхронизировать резюме"
                subtitle="подтянем твои резюме с hh — без них некуда откликаться"
              >
                <Btn
                  kind="primary"
                  size="sm"
                  onClick={() => syncM.mutate()}
                  disabled={syncM.isPending}
                >
                  {syncM.isPending ? "синхронизация…" : "Синхронизировать"}
                </Btn>
              </StepRow>

              <StepRow
                index={3}
                done={filterDone}
                active={activeStep === "filter"}
                icon={<IFilter size={15} />}
                title="Создать фильтр поиска"
                subtitle="задай должность, регион, зарплату — по ним ищем вакансии"
              >
                <Btn kind="primary" size="sm" onClick={openFilters}>
                  Создать фильтр
                </Btn>
              </StepRow>

              <StepRow
                index={4}
                done={launchDone}
                active={activeStep === "launch"}
                icon={<IPlay size={15} />}
                title="Запустить"
                subtitle="автоотклик откликается сам · ИИ-агент ещё и ведёт переписку"
              >
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Btn
                    kind="primary"
                    size="sm"
                    onClick={() => startWorkerM.mutate()}
                    disabled={startWorkerM.isPending}
                  >
                    <IPlay size={13} /> Автоотклик
                  </Btn>
                  <Btn
                    kind="soft"
                    size="sm"
                    onClick={() => startAgentM.mutate()}
                    disabled={startAgentM.isPending}
                  >
                    <ISpark size={13} /> ИИ-агент
                  </Btn>
                </div>
              </StepRow>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginTop: 20,
              }}
            >
              <button
                type="button"
                onClick={finish}
                style={{
                  border: "none",
                  background: "transparent",
                  color: "var(--muted)",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Пропустить
              </button>
              <Btn
                kind="primary"
                onClick={() => setFinalSlide(true)}
                disabled={!allDone}
              >
                Далее
              </Btn>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
