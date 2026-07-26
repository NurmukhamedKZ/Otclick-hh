import { describe, expect, it } from "vitest";
import { matchCommands, scoreCommand, type Command } from "./command-registry";

const cmd = (id: string, label: string, keywords?: string): Command => ({
  id,
  label,
  group: "Навигация",
  keywords,
});

const COMMANDS = [
  cmd("dashboard", "Главная"),
  cmd("applications", "Отклики"),
  cmd("chats", "Чаты", "переписка рекрутёр"),
  cmd("start", "Запустить автоотклик", "старт worker"),
];

describe("scoreCommand", () => {
  it("scores an empty query as a neutral match", () => {
    expect(scoreCommand(cmd("a", "Главная"), "")).toBe(0);
  });

  it("ranks a prefix match above a mid-word match", () => {
    const prefix = scoreCommand(cmd("a", "Отклики"), "откл");
    const midWord = scoreCommand(cmd("b", "Переоткрыть"), "откл");
    expect(prefix).toBeGreaterThan(midWord);
  });

  it("ranks a word-start match above a mid-word match", () => {
    const wordStart = scoreCommand(cmd("a", "Запустить автоотклик"), "авто");
    const midWord = scoreCommand(cmd("b", "Переавтоматизация"), "авто");
    expect(wordStart).toBeGreaterThan(midWord);
  });

  it("is case-insensitive", () => {
    expect(scoreCommand(cmd("a", "Главная"), "ГЛАВ")).toBeGreaterThan(-1);
  });

  it("matches on keywords too", () => {
    expect(scoreCommand(cmd("a", "Чаты", "переписка"), "переписка")).toBeGreaterThan(-1);
  });

  it("returns -1 when nothing matches", () => {
    expect(scoreCommand(cmd("a", "Главная"), "zzz")).toBe(-1);
  });
});

describe("matchCommands", () => {
  it("returns every command in original order for an empty query", () => {
    expect(matchCommands(COMMANDS, "").map((c) => c.id)).toEqual([
      "dashboard",
      "applications",
      "chats",
      "start",
    ]);
  });

  it("drops non-matching commands", () => {
    expect(matchCommands(COMMANDS, "чат").map((c) => c.id)).toEqual(["chats"]);
  });

  it("finds a command by its keywords", () => {
    expect(matchCommands(COMMANDS, "worker").map((c) => c.id)).toEqual(["start"]);
  });

  it("ignores surrounding whitespace", () => {
    expect(matchCommands(COMMANDS, "  чат  ").map((c) => c.id)).toEqual(["chats"]);
  });
});
