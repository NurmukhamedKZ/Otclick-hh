"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { computeNavCounts, type NavCounts } from "@/lib/nav-counts";
import { useChats } from "@/hooks/useChats";
import { useFormDrafts } from "@/hooks/useFormDrafts";
import { useRecruiter } from "@/hooks/useRecruiter";

/** Badge counts for the sidebar. Every source is a shared react-query entry, so
 *  mounting this next to the pages that use the same hooks costs no extra request. */
export function useNavCounts(): NavCounts {
  const supabase = useMemo(() => createClient(), []);
  // must match the chats page's default so both share one cache entry
  const { chats } = useChats(false);
  const { drafts: formDrafts } = useFormDrafts();
  const { drafts: recruiterDrafts, todos } = useRecruiter();
  const [unreadNotifications, setUnread] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let channel: ReturnType<typeof supabase.channel> | null = null;

    async function load(userId: string) {
      const { count } = await supabase
        .from("notifications")
        .select("*", { count: "exact", head: true })
        .eq("user_id", userId)
        .eq("read", false);
      if (!cancelled) setUnread(count ?? 0);
    }

    (async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user || cancelled) return;
      await load(user.id);
      channel = supabase
        .channel("nav-counts-notifications")
        .on(
          "postgres_changes",
          {
            event: "*",
            schema: "public",
            table: "notifications",
            filter: `user_id=eq.${user.id}`,
          },
          () => load(user.id),
        )
        .subscribe();
    })();

    return () => {
      cancelled = true;
      if (channel) supabase.removeChannel(channel);
    };
  }, [supabase]);

  return useMemo(
    () =>
      computeNavCounts({
        chats: chats ?? [],
        formDrafts,
        recruiterDrafts,
        todos,
        unreadNotifications,
      }),
    [chats, formDrafts, recruiterDrafts, todos, unreadNotifications],
  );
}
