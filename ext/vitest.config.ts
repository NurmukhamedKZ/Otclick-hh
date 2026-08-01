import { defineConfig } from "vitest/config";
import { WxtVitest } from "wxt/testing";

// WxtVitest stubs `wxt/browser` (webextension-polyfill refuses to load outside
// an extension) and applies WXT's aliases + env, so lib/ modules import cleanly.
export default defineConfig({
  plugins: [WxtVitest()],
  // node, not jsdom: jsdom's Uint8Array realm breaks esbuild's invariant check,
  // and every unit here tests a pure function (rendering, payload shaping,
  // storage helpers) rather than live DOM.
  test: { environment: "node", globals: true },
});
