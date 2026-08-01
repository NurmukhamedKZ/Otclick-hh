import { defineContentScript } from "wxt/sandbox";

export default defineContentScript({
  matches: ["<all_urls>"],
  allFrames: true,
  main() {
    console.log("[otclick] content script loaded");
  },
});
