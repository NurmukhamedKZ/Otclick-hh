import { browser } from "wxt/browser";

// Chat history lives in the extension, not on the server: the backend's /chat
// endpoint is stateless and takes the transcript with each request.

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

const KEY = "otc_chat_history";
export const MAX_HISTORY = 40;

export async function loadHistory(): Promise<ChatMsg[]> {
  const got = (await browser.storage.local.get(KEY)) as Record<string, unknown>;
  const list = got[KEY];
  return Array.isArray(list) ? (list as ChatMsg[]) : [];
}

export async function appendMessage(m: ChatMsg): Promise<ChatMsg[]> {
  const next = [...(await loadHistory()), m].slice(-MAX_HISTORY);
  await browser.storage.local.set({ [KEY]: next });
  return next;
}

export async function clearHistory(): Promise<void> {
  await browser.storage.local.remove(KEY);
}
