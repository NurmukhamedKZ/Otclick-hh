import { beforeEach, describe, expect, it, vi } from "vitest";

const store: Record<string, unknown> = {};
vi.mock("wxt/browser", () => ({
  browser: {
    storage: {
      local: {
        get: async (k: string) => ({ [k]: store[k] }),
        set: async (o: Record<string, unknown>) => Object.assign(store, o),
        remove: async (k: string) => {
          delete store[k];
        },
      },
    },
  },
}));

import { appendMessage, clearHistory, loadHistory, MAX_HISTORY } from "../lib/chat-store";

beforeEach(async () => {
  await clearHistory();
});

describe("chat-store", () => {
  it("starts empty", async () => {
    expect(await loadHistory()).toEqual([]);
  });

  it("appends and persists in order", async () => {
    await appendMessage({ role: "user", content: "раз" });
    const after = await appendMessage({ role: "assistant", content: "два" });
    expect(after.map((m) => m.content)).toEqual(["раз", "два"]);
    expect(await loadHistory()).toHaveLength(2);
  });

  it("keeps only the last MAX_HISTORY messages", async () => {
    for (let i = 0; i < MAX_HISTORY + 5; i++) {
      await appendMessage({ role: "user", content: `m${i}` });
    }
    const hist = await loadHistory();
    expect(hist).toHaveLength(MAX_HISTORY);
    expect(hist[0].content).toBe("m5");
  });
});
