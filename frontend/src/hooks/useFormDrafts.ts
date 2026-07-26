"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

export type FormAnswer = {
  task_id: number | string;
  question: string;
  type: "choice" | "text";
  options?: { id: string; text: string }[];
  answer_id?: string;
  answer: string;
};

export type FormDraft = {
  id: string;
  vacancy_id: string;
  resume_id: string;
  vacancy_title: string | null;
  employer_name: string | null;
  vacancy_url: string | null;
  answers: FormAnswer[];
  letter: string | null;
  status: string;
  created_at: string;
};

export const formDraftsQueryKey = ["form-drafts"] as const;

const EMPTY: FormDraft[] = [];

/** Shared between the todo page and the sidebar badge via one query cache entry. */
export function useFormDrafts() {
  const qc = useQueryClient();
  const { data, error, isLoading } = useQuery({
    queryKey: formDraftsQueryKey,
    queryFn: () => apiFetch<FormDraft[]>("/api/forms/drafts"),
    staleTime: 60_000,
  });

  const refresh = useCallback(
    () => qc.invalidateQueries({ queryKey: formDraftsQueryKey }),
    [qc],
  );

  const drop = useCallback(
    (id: string) => {
      qc.setQueryData<FormDraft[]>(formDraftsQueryKey, (prev) =>
        (prev ?? []).filter((d) => d.id !== id),
      );
    },
    [qc],
  );

  const approve = useCallback(
    async (id: string, answers: FormAnswer[], letter: string) => {
      await apiFetch(`/api/forms/drafts/${id}/approve`, {
        method: "POST",
        body: JSON.stringify({ answers, letter }),
      });
      drop(id);
    },
    [drop],
  );

  const discard = useCallback(
    async (id: string) => {
      await apiFetch(`/api/forms/drafts/${id}/discard`, { method: "POST" });
      drop(id);
    },
    [drop],
  );

  return {
    drafts: data ?? EMPTY,
    loading: isLoading,
    error: error instanceof Error ? error.message : null,
    refresh,
    approve,
    discard,
  };
}
