import { defineBackground } from "wxt/sandbox";
import { browser } from "wxt/browser";
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
    default:
      return { error: `unknown message: ${msg?.type}` };
  }
}
