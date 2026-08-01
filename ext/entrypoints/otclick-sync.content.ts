import { defineContentScript } from "wxt/sandbox";
import { browser } from "wxt/browser";
import { readSupabaseSession } from "../lib/session-sync";
import { debug } from "../lib/log";

// Auto-adopt the user's web session: whenever an Otclick page loads while the
// user is signed in there, hand the session to the extension. Firefox has no
// externally_connectable, so this content script is the only handoff path.
// The background dedupes against the stored token, so re-runs are cheap no-ops.
export default defineContentScript({
  matches: ["https://otclick.org/*", "http://localhost/*"],
  runAt: "document_idle",
  main() {
    function syncSession() {
      const session = readSupabaseSession();
      if (!session) return;
      void browser.runtime.sendMessage({
        type: "ADOPT_SESSION",
        access_token: session.access_token,
        refresh_token: session.refresh_token,
      });
      debug("otclick-sync: pushed web session to extension");
    }
    syncSession();
    // Cookies are written client-side just after sign-in; re-check shortly so a
    // fresh login on this very page is adopted without a reload.
    setTimeout(syncSession, 1500);
  },
});
