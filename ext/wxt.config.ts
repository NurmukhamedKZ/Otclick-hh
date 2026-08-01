import { defineConfig } from "wxt";

// Firefox-only build. Chrome's `key` / `externally_connectable` have no Firefox
// equivalent — the web session is adopted by a content script instead
// (entrypoints/otclick-sync.content.ts).
//
// Manifest V2 on purpose (WXT's Firefox default): Firefox MV3 makes every host
// permission optional, so the user would have to grant access per site before
// autofill works anywhere. MV2 folds `host_permissions` into `permissions` and
// grants them at install. Revisit if Mozilla announces an MV2 sunset date.
export default defineConfig({
  manifest: {
    name: "Otclick Autofill",
    description: "Заполняет анкеты вашими данными. Отправляете вы сами.",
    version: "0.1.0",
    browser_specific_settings: {
      gecko: { id: "autofill@otclick.org", strict_min_version: "128.0" },
    },
    permissions: ["storage", "webNavigation"],
    host_permissions: [
      "https://docs.google.com/*",
      "https://forms.gle/*",
      "https://forms.yandex.ru/*",
      "https://forms.yandex.kz/*",
      "https://forms.office.com/*",
      "http://localhost/*",
    ],
    optional_host_permissions: ["<all_urls>"],
    action: {},
    commands: {
      "trigger-autofill": {
        suggested_key: { default: "Alt+Shift+O" },
        description: "Заполнить эту страницу",
      },
    },
    web_accessible_resources: [{ resources: ["fonts/*"], matches: ["<all_urls>"] }],
    icons: { 16: "/icon/16.png", 32: "/icon/32.png", 48: "/icon/48.png", 128: "/icon/128.png" },
  },
});
