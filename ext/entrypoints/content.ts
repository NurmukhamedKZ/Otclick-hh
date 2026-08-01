import { defineContentScript } from "wxt/sandbox";
import { browser } from "wxt/browser";
import { applyFill, snapshotWithOptions } from "../lib/snapshot";
import { mergeFrameFields, withLabels, type FillResponse, type FilledField } from "../lib/api";
import { renderMarks } from "../lib/marks";
import { error } from "../lib/log";

export default defineContentScript({
  matches: ["<all_urls>"],
  allFrames: true,
  main() {
    browser.runtime.onMessage.addListener((msg: unknown) => {
      const type = (msg as { type?: string })?.type;
      if (type === "TOGGLE_PANEL" || type === "TRIGGER_AUTOFILL") void runFill();
      return undefined;
    });
  },
});

/** Fields applied by the last run, kept for the qa_memory edit diff. */
let lastApplied: (FilledField & { label: string })[] = [];

async function runFill(): Promise<void> {
  try {
    const els = await snapshotWithOptions();
    if (els.length === 0) return;
    const resp = (await browser.runtime.sendMessage({
      type: "FILL_PAGE",
      url: location.href,
      page_text: document.body.innerText,
      // frame_id 0 only: v1 fills the top frame. The frames[] envelope is
      // already in place on both sides for the cross-frame fan-out.
      frames: [{ frame_id: 0, snapshot: els }],
    })) as FillResponse & { error?: string };
    if (resp?.error) throw new Error(resp.error);
    const applied = await applyFill(mergeFrameFields(resp, 0) as never);
    lastApplied = withLabels(applied as never, els as never);
    renderMarks(lastApplied);
  } catch (e) {
    error("autofill failed:", e);
  }
}
