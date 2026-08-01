import { defineBackground } from "wxt/sandbox";
import { browser } from "wxt/browser";
import { buildFillPayload, callFill, fetchContext, resumeFileUrl } from "../lib/api";
import { getValidJwt, openWebSignIn, persistExternalSession, signOut } from "../lib/auth";
import { debug, error } from "../lib/log";

const APP_BASE = (import.meta.env.VITE_APP_BASE as string) ?? "http://localhost:3000";

interface Msg {
  type: string;
  [key: string]: unknown;
}

export default defineBackground(() => {
  browser.runtime.onMessage.addListener((msg: unknown, _sender, sendResponse) => {
    void handle(msg as Msg)
      .then(sendResponse)
      .catch((e) => sendResponse({ error: String(e) }));
    return true; // keep the channel open for the async response
  });

  browser.action.onClicked.addListener(async (tab) => {
    if (tab.id != null) await browser.tabs.sendMessage(tab.id, { type: "TOGGLE_PANEL" });
  });

  browser.commands.onCommand.addListener(async (command) => {
    if (command !== "trigger-autofill") return;
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    if (tab?.id != null) await browser.tabs.sendMessage(tab.id, { type: "TRIGGER_AUTOFILL" });
  });
});

async function handle(msg: Msg): Promise<unknown> {
  switch (msg?.type) {
    case "AUTH_STATUS": {
      const jwt = await getValidJwt();
      const { email } = (await browser.storage.local.get("email")) as { email?: string };
      return { loggedIn: Boolean(jwt), email: email ?? "" };
    }
    case "SIGN_IN":
      openWebSignIn();
      return { ok: true };
    case "SIGN_OUT":
      await signOut();
      return { ok: true };
    case "OPEN_APP":
      await browser.tabs.create({ url: `${APP_BASE}${String(msg.path ?? "")}` });
      return { ok: true };
    case "ADOPT_SESSION": {
      // The content script fires on every Otclick page load; re-adopting an
      // identical session each time would burn a GoTrue round trip per navigation.
      const { jwt } = (await browser.storage.local.get("jwt")) as { jwt?: string };
      if (jwt && jwt === msg.access_token) return { ok: true, unchanged: true };
      try {
        const email = await persistExternalSession(
          String(msg.access_token ?? ""),
          String(msg.refresh_token ?? ""),
        );
        debug("background: adopted web session for", email);
        return { ok: true, email };
      } catch (e) {
        error("background: session adoption failed:", e);
        return { ok: false };
      }
    }
    case "CONTEXT": {
      const ctx = await fetchContext();
      return {
        facts: ctx.facts,
        resume: ctx.has_resume_file
          ? { url: resumeFileUrl(), filename: ctx.resume_filename ?? "resume.pdf" }
          : null,
      };
    }
    case "FETCH_FILE": {
      // The page can't send our Authorization header (and the API origin is
      // cross-origin to the form), so the download happens here and the bytes
      // travel back base64-encoded — see snapshot.ts fetchFileViaBackground.
      const url = String(msg.url ?? "");
      if (!url.startsWith(resumeFileUrl())) return { ok: false };
      const jwt = await getValidJwt();
      if (!jwt) return { ok: false };
      const r = await fetch(url, { headers: { Authorization: `Bearer ${jwt}` } });
      if (!r.ok) return { ok: false };
      const buf = new Uint8Array(await r.arrayBuffer());
      let bin = "";
      for (const byte of buf) bin += String.fromCharCode(byte);
      return {
        ok: true,
        b64: btoa(bin),
        contentType: r.headers.get("content-type") ?? "application/pdf",
      };
    }
    case "FILL_PAGE":
      return await callFill(
        buildFillPayload({
          url: String(msg.url ?? ""),
          pageText: String(msg.page_text ?? ""),
          frames: (msg.frames ?? []) as { frame_id: number; snapshot: unknown[] }[],
        }),
      );
    default:
      return { error: `unknown message: ${msg?.type}` };
  }
}
