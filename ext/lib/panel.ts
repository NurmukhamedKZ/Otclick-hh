// In-page panel: three tabs (autofill / chat / settings) mounted in a shadow
// root so the host page's CSS can't reach it. Kept deliberately small — the
// OtclickUS sidebar it replaces carried ATS, resume tailoring and agent UI that
// this product doesn't have.

export type Tab = "fill" | "chat" | "settings";
export type FillState = "idle" | "working" | "done" | "error";

export interface PanelCallbacks {
  onFill: () => void;
  onSignIn: () => void;
  onSignOut: () => void;
  onSend: (text: string) => Promise<string>;
  onSaveEdits: () => void;
}

export interface PanelController {
  toggle: () => void;
  setAuth: (loggedIn: boolean, email: string) => void;
  setState: (s: FillState, data?: { error?: string; filled?: number }) => void;
  setFilled: (fields: { label: string; value: string; source: string }[]) => void;
  appendChat: (role: "user" | "assistant", text: string) => void;
  setTab: (t: Tab) => void;
}

const HOST_ID = "otclick-panel-root";

export function esc(s: string): string {
  return s.replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
}

export function renderFilledList(
  fields: { label: string; value: string; source: string }[],
): string {
  if (fields.length === 0) return `<p class="otc-empty">Пока ничего не заполнено</p>`;
  return `<ul class="otc-list">${fields
    .map(
      (f) =>
        `<li class="otc-src-${esc(f.source)}"><span class="otc-k">${esc(f.label)}</span>` +
        `<span class="otc-v">${esc(f.value)}</span></li>`,
    )
    .join("")}</ul>`;
}

export function statusText(s: FillState, data?: { error?: string; filled?: number }): string {
  switch (s) {
    case "working":
      return "Заполняю…";
    case "done":
      return `Готово: ${data?.filled ?? 0} полей. Проверьте и отправьте форму сами.`;
    case "error":
      return data?.error ?? "Ошибка";
    default:
      return "";
  }
}

const CSS = `
:host { all: initial; }
.otc-wrap { position: fixed; top: 0; right: 0; width: 360px; height: 100vh; z-index: 2147483647;
  background: #fff; color: #111; font: 14px/1.45 system-ui, -apple-system, sans-serif;
  box-shadow: -2px 0 12px rgba(0,0,0,.15); display: flex; flex-direction: column; }
.otc-wrap[hidden] { display: none; }
.otc-tabs { display: flex; border-bottom: 1px solid #e5e5e5; }
.otc-tabs button { flex: 1; padding: 10px; border: 0; background: none; cursor: pointer; font: inherit; }
.otc-tabs button[aria-selected="true"] { font-weight: 600; box-shadow: inset 0 -2px 0 #111; }
.otc-body { flex: 1; overflow: auto; padding: 12px; }
.otc-body[hidden] { display: none; }
.otc-status { margin: 0 0 10px; color: #444; }
.otc-list { list-style: none; margin: 0; padding: 0; }
.otc-list li { padding: 6px 0; border-bottom: 1px solid #f0f0f0; display: flex; gap: 8px; }
.otc-k { flex: 0 0 42%; color: #666; }
.otc-v { flex: 1; overflow-wrap: anywhere; }
.otc-src-ai .otc-v { color: #6d28d9; }
.otc-empty { color: #888; }
.otc-foot { padding: 12px; border-top: 1px solid #e5e5e5; display: flex; gap: 8px; }
.otc-foot[hidden] { display: none; }
button.otc-primary { padding: 8px 14px; background: #111; color: #fff; border: 0; border-radius: 6px;
  cursor: pointer; font: inherit; }
button.otc-primary[disabled] { opacity: .5; cursor: default; }
.otc-chat-msg { margin-bottom: 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
.otc-chat-msg.user { text-align: right; color: #333; }
.otc-chat-input { flex: 1; padding: 8px; border: 1px solid #d4d4d4; border-radius: 6px; font: inherit; }
`;

export function mountPanel(cb: PanelCallbacks): PanelController {
  document.getElementById(HOST_ID)?.remove();
  const host = document.createElement("div");
  host.id = HOST_ID;
  const root = host.attachShadow({ mode: "open" });
  document.documentElement.appendChild(host);

  root.innerHTML = `
    <style>${CSS}</style>
    <div class="otc-wrap" hidden>
      <div class="otc-tabs">
        <button data-tab="fill" aria-selected="true">Заполнение</button>
        <button data-tab="chat" aria-selected="false">Чат</button>
        <button data-tab="settings" aria-selected="false">Настройки</button>
      </div>
      <div class="otc-body" data-pane="fill">
        <p class="otc-status"></p>
        <div class="otc-filled"></div>
      </div>
      <div class="otc-body" data-pane="chat" hidden><div class="otc-chat"></div></div>
      <div class="otc-body" data-pane="settings" hidden>
        <p class="otc-email"></p>
        <button class="otc-signin otc-primary">Войти</button>
        <button class="otc-signout otc-primary" hidden>Выйти</button>
      </div>
      <div class="otc-foot" data-foot="fill">
        <button class="otc-fill otc-primary">Заполнить</button>
        <button class="otc-save otc-primary" hidden>Сохранить правки</button>
      </div>
      <div class="otc-foot" data-foot="chat" hidden>
        <input class="otc-chat-input" placeholder="Спросите что угодно" />
        <button class="otc-send otc-primary">→</button>
      </div>
      <div class="otc-foot" data-foot="settings" hidden></div>
    </div>`;

  const $ = <T extends Element>(sel: string) => root.querySelector(sel) as T;
  const wrap = $<HTMLDivElement>(".otc-wrap");

  const setTab = (tab: Tab) => {
    root
      .querySelectorAll("[data-tab]")
      .forEach((b) => b.setAttribute("aria-selected", String(b.getAttribute("data-tab") === tab)));
    root
      .querySelectorAll("[data-pane]")
      .forEach((p) => ((p as HTMLElement).hidden = p.getAttribute("data-pane") !== tab));
    root
      .querySelectorAll("[data-foot]")
      .forEach((f) => ((f as HTMLElement).hidden = f.getAttribute("data-foot") !== tab));
  };
  root
    .querySelectorAll("[data-tab]")
    .forEach((b) => b.addEventListener("click", () => setTab(b.getAttribute("data-tab") as Tab)));

  $(".otc-fill").addEventListener("click", () => cb.onFill());
  $(".otc-save").addEventListener("click", () => cb.onSaveEdits());
  $(".otc-signin").addEventListener("click", () => cb.onSignIn());
  $(".otc-signout").addEventListener("click", () => cb.onSignOut());

  const chatBox = $<HTMLDivElement>(".otc-chat");
  const appendChat = (role: "user" | "assistant", text: string) => {
    const div = document.createElement("div");
    div.className = `otc-chat-msg ${role}`;
    div.textContent = text;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
  };

  const sendBtn = $<HTMLButtonElement>(".otc-send");
  const input = $<HTMLInputElement>(".otc-chat-input");
  const send = async () => {
    const text = input.value.trim();
    if (!text || sendBtn.disabled) return;
    input.value = "";
    appendChat("user", text);
    sendBtn.disabled = true;
    try {
      appendChat("assistant", await cb.onSend(text));
    } finally {
      sendBtn.disabled = false;
    }
  };
  sendBtn.addEventListener("click", () => void send());
  input.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Enter") void send();
  });

  return {
    toggle: () => (wrap.hidden = !wrap.hidden),
    setTab,
    setAuth: (loggedIn, email) => {
      $(".otc-email").textContent = loggedIn ? email : "Вы не вошли";
      ($(".otc-signin") as HTMLElement).hidden = loggedIn;
      ($(".otc-signout") as HTMLElement).hidden = !loggedIn;
    },
    setState: (s, data) => {
      $(".otc-status").textContent = statusText(s, data);
      ($(".otc-save") as HTMLElement).hidden = s !== "done";
      ($(".otc-fill") as HTMLButtonElement).disabled = s === "working";
    },
    setFilled: (fields) => {
      $(".otc-filled").innerHTML = renderFilledList(fields);
    },
    appendChat,
  };
}
