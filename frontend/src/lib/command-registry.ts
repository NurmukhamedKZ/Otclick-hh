export type CommandGroup = "Навигация" | "Действия" | "Отклики";

export type Command = {
  id: string;
  label: string;
  group: CommandGroup;
  keywords?: string;
  hint?: string;
};

/** -1 = no match. Higher is a better match. */
export function scoreCommand(cmd: Command, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 0;

  const haystack = `${cmd.label} ${cmd.keywords ?? ""}`.toLowerCase();
  const idx = haystack.indexOf(q);
  if (idx < 0) return -1;
  if (idx === 0) return 3;
  if (haystack[idx - 1] === " ") return 2;
  return 1;
}

export function matchCommands(commands: Command[], query: string): Command[] {
  return commands
    .map((cmd, i) => ({ cmd, i, score: scoreCommand(cmd, query) }))
    .filter((e) => e.score >= 0)
    .sort((a, b) => (b.score - a.score) || (a.i - b.i))
    .map((e) => e.cmd);
}
