"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type {
  Filter,
  FilterCreate,
  FilterPreview,
  FilterSuggestion,
} from "@/lib/types";

export function useFilters() {
  const [items, setItems] = useState<Filter[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<Filter[]>("/api/filters");
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const create = useCallback(async (body: FilterCreate) => {
    const row = await apiFetch<Filter>("/api/filters", {
      method: "POST",
      body: JSON.stringify(body),
    });
    setItems((prev) => (prev ? [row, ...prev] : [row]));
    return row;
  }, []);

  const update = useCallback(
    async (id: string, patch: Partial<FilterCreate>) => {
      const row = await apiFetch<Filter>(`/api/filters/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setItems((prev) =>
        prev ? prev.map((f) => (f.id === id ? row : f)) : prev,
      );
      return row;
    },
    [],
  );

  const remove = useCallback(async (id: string) => {
    await apiFetch(`/api/filters/${id}`, { method: "DELETE" });
    setItems((prev) => (prev ? prev.filter((f) => f.id !== id) : prev));
  }, []);

  const preview = useCallback(async (id: string) => {
    return apiFetch<FilterPreview>(`/api/filters/${id}/preview`);
  }, []);

  const suggest = useCallback(async (resumeId: string) => {
    return apiFetch<FilterSuggestion[]>("/api/filters/auto", {
      method: "POST",
      body: JSON.stringify({ resume_id: resumeId }),
    });
  }, []);

  return { items, error, reload: load, create, update, remove, preview, suggest };
}
