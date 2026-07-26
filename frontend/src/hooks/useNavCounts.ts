"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { computeNavCounts, type NavCounts } from "@/lib/nav-counts";
import { useChats } from "@/hooks/useChats";
import { useFormDrafts } from "@/hooks/useFormDrafts";
import { useRecruiter } from "@/hooks/useRecruiter";

const EMPTY: NavCounts = { chats: 0, todo: 0, notifications: 0 };

export function useNavCounts(): NavCounts {
  const supabase = useMemo(() => createClient(), []);
  const { chats } = useChats(false);
  const { drafts: formDrafts } = useFormDrafts();
  const { drafts: recruiterDrafts, todos } = useRecruiter();
  const [unreadNotifications, setUnread] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const { count } = await supabase
        .from("notifications")
        .select("*", { count: "exact", head: true })
        .eq("read", false);
      if (!cancelled) setUnread(count ?? 0);
    }
    load();
    const channel = supabase
      .channel("nav-counts-notifications")
      .on("postgres_changes", { event: "*", schema: "public", table: "notifications" }, load)
      .subscribe();
    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return useMemo(() => {
    if (!chats && !formDrafts && !recruiterDrafts && !todos) return EMPTY;
    return computeNavCounts({
      chats: chats ?? [],
      formDrafts: formDrafts ?? [],
      recruiterDrafts: recruiterDrafts ?? [],
      todos: todos ?? [],
      unreadNotifications,
    });
  }, [chats, formDrafts, recruiterDrafts, todos, unreadNotifications]);
}
