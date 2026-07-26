export type NavCounts = { chats: number; todo: number; notifications: number };

export type NavCountsInput = {
  chats: { unread: number }[];
  formDrafts: unknown[];
  recruiterDrafts: unknown[];
  todos: unknown[];
  unreadNotifications: number;
};

export function computeNavCounts(input: NavCountsInput): NavCounts {
  return {
    chats: input.chats.reduce((sum, c) => sum + (c.unread ?? 0), 0),
    todo: input.formDrafts.length + input.recruiterDrafts.length + input.todos.length,
    notifications: input.unreadNotifications,
  };
}

/** Badge text, or null when the badge should not render at all. */
export function formatBadge(n: number): string | null {
  if (n < 1) return null;
  return n > 99 ? "99+" : String(n);
}
