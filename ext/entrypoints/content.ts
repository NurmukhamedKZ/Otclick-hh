import { defineContentScript } from "wxt/sandbox";
import { browser } from "wxt/browser";
import { applyFill, findEl, snapshotWithOptions } from "../lib/snapshot";
import { mergeFrameFields, withLabels, type FillResponse, type FilledField } from "../lib/api";
import { readFieldValue, renderMarks } from "../lib/marks";
import { deterministicFields } from "../lib/deterministic-fill";
import { mountPanel, type PanelController } from "../lib/panel";
import { appendMessage, loadHistory } from "../lib/chat-store";
import { collectEdits } from "../lib/edits";
import { error } from "../lib/log";

/** Fields applied by the last run, kept for the qa_memory edit diff. */
let lastApplied: (FilledField & { label: string })[] = [];
let panel: PanelController | null = null;

export default defineContentScript({
  matches: ["<all_urls>"],
  allFrames: true,
  async main() {
    browser.runtime.onMessage.addListener((msg: unknown) => {
      const type = (msg as { type?: string })?.type;
      if (type === "TOGGLE_PANEL") panel?.toggle();
      if (type === "TRIGGER_AUTOFILL") void runFill();
      return undefined;
    });

    // The panel lives in the top frame only; nested frames just fill.
    if (window.top !== window) return;
    panel = mountPanel({
      onFill: () => void runFill(),
      onSignIn: () => void browser.runtime.sendMessage({ type: "SIGN_IN" }),
      onSignOut: () => {
        void browser.runtime.sendMessage({ type: "SIGN_OUT" });
        panel?.setAuth(false, "");
      },
      onSend: sendChat,
      onSaveEdits: () => void saveEdits(),
    });
    for (const m of await loadHistory()) panel.appendChat(m.role, m.content);
    await refreshAuth();
  },
});

/** One chat turn: the transcript lives here, the backend stays stateless. The
 *  open page's text goes along so "что тут ответить?" works without pasting. */
async function sendChat(text: string): Promise<string> {
  const history = await appendMessage({ role: "user", content: text });
  const resp = (await browser.runtime.sendMessage({
    type: "CHAT",
    messages: history,
    page_text: document.body.innerText.slice(0, 20_000),
  })) as { answer?: string; error?: string };
  const answer = resp?.answer ?? "Не удалось получить ответ.";
  await appendMessage({ role: "assistant", content: answer });
  return answer;
}

async function refreshAuth(): Promise<void> {
  const auth = (await browser.runtime.sendMessage({ type: "AUTH_STATUS" })) as {
    loggedIn?: boolean;
    email?: string;
  };
  panel?.setAuth(Boolean(auth?.loggedIn), auth?.email ?? "");
}

async function runFill(): Promise<void> {
  panel?.setState("working");
  try {
    const els = await snapshotWithOptions();
    if (els.length === 0) {
      panel?.setState("error", { error: "Полей на странице не найдено." });
      return;
    }

    // Verbatim facts and the resume file land first — no LLM round trip, so the
    // user sees the form move immediately.
    const ctx = (await browser.runtime.sendMessage({ type: "CONTEXT" })) as {
      facts?: Record<string, string>;
      resume?: { url: string; filename: string } | null;
      error?: string;
    };
    if (ctx?.error) throw new Error(ctx.error);
    const quick = deterministicFields(els as never, ctx.facts ?? {}, ctx.resume ?? undefined);
    lastApplied = [];
    if (quick.length > 0) {
      const appliedQuick = await applyFill(quick as never);
      lastApplied = withLabels(appliedQuick as never, els as never);
      show();
    }

    const remaining = els.filter((el) => !quick.some((q) => q.ref === el.ref));
    if (remaining.length > 0) {
      const resp = (await browser.runtime.sendMessage({
        type: "FILL_PAGE",
        url: location.href,
        page_text: document.body.innerText,
        // frame_id 0 only: v1 fills the top frame. The frames[] envelope is
        // already in place on both sides for the cross-frame fan-out.
        frames: [{ frame_id: 0, snapshot: remaining }],
      })) as FillResponse & { error?: string };
      if (resp?.error) throw new Error(resp.error);
      const applied = await applyFill(mergeFrameFields(resp, 0) as never);
      lastApplied = [...lastApplied, ...withLabels(applied as never, els as never)];
      show();
    }
    panel?.setState("done", { filled: lastApplied.length });
  } catch (e) {
    error("autofill failed:", e);
    if (String(e).includes("unauthorized")) {
      panel?.setState("error", { error: "Войдите в аккаунт Otclick." });
      panel?.setTab("settings");
    } else {
      panel?.setState("error", { error: "Не удалось заполнить. Попробуйте ещё раз." });
    }
  }
}

/** Whatever the user corrected after the fill becomes Q&A memory, so the next
 *  form (and the hh worker's form drafts) reuse their wording, not the model's. */
async function saveEdits(): Promise<void> {
  try {
    const current = lastApplied.map((f) => {
      const node = findEl(f.selector);
      return { ref: f.ref, label: f.label, value: node ? readFieldValue(node).trim() : "" };
    });
    const items = collectEdits(lastApplied, current);
    if (items.length === 0) {
      panel?.setState("saved", { filled: 0 });
      return;
    }
    const resp = (await browser.runtime.sendMessage({ type: "SAVE_QA", items })) as {
      saved?: number;
      error?: string;
    };
    if (resp?.error) throw new Error(resp.error);
    panel?.setState("saved", { filled: resp?.saved ?? 0 });
  } catch (e) {
    error("saving edits failed:", e);
    panel?.setState("error", { error: "Не удалось сохранить правки." });
  }
}

/** Push the current applied set to both surfaces: in-page badges and the panel. */
function show(): void {
  renderMarks(lastApplied);
  panel?.setFilled(lastApplied);
}
