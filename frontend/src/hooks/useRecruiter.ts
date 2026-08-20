"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

export type Draft = {
  id: string;
  negotiation_id: string;
  draft_text: string;
  reason: string | null;
  question_text: string | null;
  vacancy_id: string | null;
  vacancy_title: string | null;
  employer_name: string | null;
  created_at: string;
};

export type Todo = {
  id: string;
  negotiation_id: string;
  title: string;
  detail: string | null;
  link: string | null;
  vacancy_id: string | null;
  vacancy_title: string | null;
  employer_name: string | null;
  created_at: string;
};

export type QuestionSet = {
  id: string;
  negotiation_id: string;
  questions: string[];
  reason: string | null;
  question_text: string | null;
  vacancy_id: string | null;
  vacancy_title: string | null;
  employer_name: string | null;
  created_at: string;
};

type RecruiterData = { drafts: Draft[]; todos: Todo[]; questions: QuestionSet[] };

export const recruiterQueryKey = ["recruiter"] as const;

const EMPTY: RecruiterData = { drafts: [], todos: [], questions: [] };

/** Shared between the todo page and the sidebar badge via one query cache entry. */
export function useRecruiter() {
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({
    queryKey: recruiterQueryKey,
    queryFn: async (): Promise<RecruiterData> => {
      const [drafts, todos, questions] = await Promise.all([
        apiFetch<Draft[]>("/api/recruiter/drafts"),
        apiFetch<Todo[]>("/api/recruiter/todos"),
        apiFetch<QuestionSet[]>("/api/recruiter/questions"),
      ]);
      return { drafts, todos, questions };
    },
    staleTime: 60_000,
  });

  const refresh = useCallback(
    () => qc.invalidateQueries({ queryKey: recruiterQueryKey }),
    [qc],
  );

  const patch = useCallback(
    (fn: (prev: RecruiterData) => RecruiterData) => {
      qc.setQueryData<RecruiterData>(recruiterQueryKey, (prev) => fn(prev ?? EMPTY));
    },
    [qc],
  );

  const sendDraft = useCallback(
    async (id: string, message: string) => {
      await apiFetch(`/api/recruiter/drafts/${id}/send`, {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      patch((prev) => ({ ...prev, drafts: prev.drafts.filter((d) => d.id !== id) }));
    },
    [patch],
  );

  const discardDraft = useCallback(
    async (id: string) => {
      await apiFetch(`/api/recruiter/drafts/${id}/discard`, { method: "POST" });
      patch((prev) => ({ ...prev, drafts: prev.drafts.filter((d) => d.id !== id) }));
    },
    [patch],
  );

  const resolveTodo = useCallback(
    async (id: string, action: "done" | "dismiss") => {
      await apiFetch(`/api/recruiter/todos/${id}/${action}`, { method: "POST" });
      patch((prev) => ({ ...prev, todos: prev.todos.filter((t) => t.id !== id) }));
    },
    [patch],
  );

  const answerQuestions = useCallback(
    async (id: string, answers: string[]) => {
      await apiFetch(`/api/recruiter/questions/${id}/answer`, {
        method: "POST",
        body: JSON.stringify({ answers }),
      });
      patch((prev) => ({
        ...prev,
        questions: prev.questions.filter((q) => q.id !== id),
      }));
    },
    [patch],
  );

  const discardQuestion = useCallback(
    async (id: string) => {
      await apiFetch(`/api/recruiter/questions/${id}/discard`, { method: "POST" });
      patch((prev) => ({
        ...prev,
        questions: prev.questions.filter((q) => q.id !== id),
      }));
    },
    [patch],
  );

  return {
    drafts: data?.drafts ?? EMPTY.drafts,
    todos: data?.todos ?? EMPTY.todos,
    questions: data?.questions ?? EMPTY.questions,
    loading: isLoading,
    error: error instanceof Error ? error.message : null,
    refresh,
    sendDraft,
    discardDraft,
    resolveTodo,
    answerQuestions,
    discardQuestion,
  };
}
