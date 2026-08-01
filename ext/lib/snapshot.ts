// Observe the page's fillable fields and apply backend-decided values.
//
// OOP, ported from agent/observer.py::PageObserver. The agent runs server-side
// on Playwright (frame.evaluate); the extension runs INSIDE the page, so the
// same DOM heuristics live here as direct-DOM TS — no evaluate wrapper.
//   PageObserver  — read the live form into SnapshotEl[] (facts only).
//   FormFiller    — type backend values into the live form. NEVER submits.
// Every signal the agent's _SNAPSHOT_JS captures is mirrored here: upgraded
// required-detection (aria + visual marker), constraints, errors, autocomplete,
// placeholder, name, value, and same-origin iframe walk.

import { warn } from "./log";
import { perfMark } from "./perf";
import { browser } from "wxt/browser";

export interface SnapshotEl {
  ref: string;
  label: string;
  field_type: string;
  selector: string;
  options: string[];
  required: boolean;
  // --- signals ported from PageObserver (additive; backend reads via .get) ---
  autocomplete: string | null;
  placeholder: string | null;
  name: string | null;
  value: string | null;
  maxlength: number | null;
  pattern: string | null;
  accept: string | null; // file-input accepted types
  error: string | null; // visible aria-describedby text (a shown validation error)
  section: string | null; // nearest heading / fieldset legend
}

// ── frame helpers ───────────────────────────────────────────────────────────
// Cross-origin ATS embed iframes (Greenhouse job-boards.greenhouse.io, iCIMS,
// Workday) get their OWN content-script instance via allFrames:true in the
// manifest — so this helper only needs to walk SAME-ORIGIN children (nested
// same-origin iframes inside the current frame). Cross-origin frames are
// unreachable here (SecurityError) and silently skipped; their content script
// snapshots them independently.
const collectDocuments = (root: Document = document): Document[] => {
  const docs: Document[] = [root];
  for (const frame of Array.from(root.querySelectorAll("iframe, frame"))) {
    let inner: Document | null = null;
    try {
      inner = (frame as HTMLIFrameElement).contentDocument;
    } catch {
      inner = null; // cross-origin — SecurityError
    }
    if (inner) docs.push(...collectDocuments(inner));
  }
  return docs;
};

// Every Document AND open ShadowRoot reachable from root (recursively: open
// shadow roots of every element + same-origin child frames). Web-component ATS
// (SmartRecruiters `spl-*` Stencil controls, etc.) bury the real
// <input>/<textarea>/<button> inside each component's shadow root;
// querySelectorAll does NOT pierce a shadow boundary, so a plain document walk
// sees only light-DOM nodes (outer nav/footer buttons) and misses every form
// field. Closed shadow roots are unreachable (.shadowRoot === null) and skipped.
const collectRoots = (
  root: Document | ShadowRoot = document,
): (Document | ShadowRoot)[] => {
  const roots: (Document | ShadowRoot)[] = [root];
  for (const el of Array.from(root.querySelectorAll("*"))) {
    const sr = (el as HTMLElement).shadowRoot;
    if (sr) roots.push(...collectRoots(sr));
    if (el.tagName === "IFRAME" || el.tagName === "FRAME") {
      let inner: Document | null = null;
      try {
        inner = (el as HTMLIFrameElement).contentDocument;
      } catch {
        inner = null; // cross-origin — SecurityError
      }
      if (inner) roots.push(...collectRoots(inner));
    }
  }
  return roots;
};

// Read an attribute off the shadow HOST chain — a control inside a web
// component's shadow root inherits its label/required state from the host
// element's attributes (e.g. `<spl-input label="First name" required>`), not
// from the inner <input>. Climbs nested shadow hosts; null in light DOM.
const shadowHostAttr = (el: Element, attr: string): string | null => {
  let root = el.getRootNode();
  for (let d = 0; d < 4 && root instanceof ShadowRoot; d++) {
    const v = root.host.getAttribute(attr);
    if (v !== null) return v;
    root = root.host.getRootNode();
  }
  return null;
};

// Element-owned document/window — every helper resolves labels/options against
// the element's OWN frame, never the global `document` (which is the top frame).
const ownerWin = (el: Element): Window =>
  el.ownerDocument.defaultView ?? window;
const ownerStyle = (el: Element): CSSStyleDeclaration =>
  ownerWin(el).getComputedStyle(el as HTMLElement);

// ── visibility ────────────────────────────────────────────────────────────
const isVisible = (el: Element): boolean => {
  const s = ownerStyle(el);
  if (s.display === "none" || s.visibility === "hidden") return false;
  if ((el as HTMLElement).offsetParent === null && el.tagName !== "BODY") return false;
  return true;
};

const isFileInput = (el: Element): boolean =>
  el.tagName === "INPUT" && (el.getAttribute("type") || "").toLowerCase() === "file";

/** True if an ANCESTOR is display:none/visibility:hidden (e.g. an inactive
 *  wizard step) — vs the element merely hiding itself (a styled drag-drop file
 *  input). A file input is surfaced when self-hidden but NOT when ancestor-hidden,
 *  so future steps don't leak into the current one. Ports observer.py::hiddenAncestor. */
const hiddenAncestor = (el: Element): boolean => {
  let p = el.parentElement;
  while (p) {
    const s = ownerStyle(p);
    if (s.display === "none" || s.visibility === "hidden") return true;
    p = p.parentElement;
  }
  return false;
};

const _isPlaceholder = (v: string) =>
  v === "" || /^[-–—]+$/u.test(v) || /^select/i.test(v) || /^choose/i.test(v);

// ── label resolution (kept from the original port of form_snapshot.py) ──────
/** Question text often sits in a sibling <label>/<legend> within a per-field
 *  container (no `for`, input has no matching id) — e.g. Ashby custom
 *  questions. Climb until the scope would swallow another field, then take the
 *  first label/legend that wraps no control and isn't el's own wrapper. */
const containerLabel = (el: Element): string => {
  let scope: Element | null = el.parentElement;
  for (let d = 0; scope && d < 5 && scope.tagName !== "FORM" && scope.tagName !== "BODY";
       d++, scope = scope.parentElement) {
    let foreign = false;
    for (const inp of Array.from(scope.querySelectorAll("input, select, textarea"))) {
      if (inp !== el) { foreign = true; break; }
    }
    if (foreign) return "";
    for (const c of Array.from(scope.querySelectorAll("label, legend"))) {
      if (!c.querySelector("input, select, textarea") && !c.contains(el) && c.textContent?.trim())
        return c.textContent;
    }
  }
  return "";
};

/** Join every id in a space-separated aria-labelledby list, resolving each
 *  in `root` and skipping dangling ids — the standard ARIA multi-id pattern
 *  (Google Forms: `aria-labelledby="<heading-id> <required-marker-id>"`).
 *  A single id keeps behaving exactly as before (one-element join). */
export const resolveLabelledBy = (ids: string, root: Document | ShadowRoot): string =>
  ids
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => root.querySelector("#" + CSS.escape(id))?.textContent)
    .filter((t): t is string => !!t && !!t.trim())
    .join(" ");

const accName = (el: Element): string => {
  const e = el as HTMLElement;
  // Label refs (`for=`, `aria-labelledby`) resolve within the element's OWN
  // root — a ShadowRoot for a web-component control, the Document otherwise.
  const root = e.getRootNode() as Document | ShadowRoot;
  if (e.id) {
    const lab = root.querySelector('label[for="' + CSS.escape(e.id) + '"]');
    if (lab && lab.textContent?.trim()) return lab.textContent;
  }
  const wrap = e.closest("label");
  if (wrap && wrap.textContent?.trim()) return wrap.textContent;
  if (e.getAttribute("aria-label")) return e.getAttribute("aria-label")!;
  const lb = e.getAttribute("aria-labelledby");
  if (lb) { const t = resolveLabelledBy(lb, root); if (t) return t; }
  const tag = e.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") {
    const cl = containerLabel(e);
    if (cl) return cl;
    // Web-component control: the inner <input> sits in the host's shadow root
    // and the visible label is the HOST's `label`/`aria-label` attribute —
    // read it across the shadow boundary before falling back to placeholder.
    const host = shadowHostAttr(e, "label") ?? shadowHostAttr(e, "aria-label");
    if (host?.trim()) return host;
  }
  if (e.getAttribute("placeholder")) return e.getAttribute("placeholder")!;
  if (e.getAttribute("name")) return e.getAttribute("name")!;
  return (e.textContent || "").trim();
};

const durable = (el: Element): string => {
  const e = el as HTMLElement;
  if (e.id) return "#" + CSS.escape(e.id);
  const name = e.getAttribute("name");
  const type = (e.getAttribute("type") || "").toLowerCase();
  // Radio/checkbox groups share one name — disambiguate by value, or every
  // selector resolves to the group's FIRST input.
  if (name && (type === "radio" || type === "checkbox") && e.getAttribute("value") !== null)
    return 'input[name="' + name + '"][value="' + e.getAttribute("value") + '"]';
  if (name) return e.tagName.toLowerCase() + '[name="' + name + '"]';
  const parts: string[] = [];
  let node: Element | null = el;
  while (node && node.nodeType === 1 && node.tagName !== "BODY") {
    let i = 1, sib: Element | null = node;
    while ((sib = sib.previousElementSibling)) { if (sib.tagName === node.tagName) i++; }
    parts.unshift(node.tagName.toLowerCase() + ":nth-of-type(" + i + ")");
    node = node.parentElement;
  }
  return parts.join(" > ");
};

/** Sibling radios sharing this element's `name` (same document) — the mutually-
 *  exclusive option set for one logical question ("Are you proficient in
 *  English?" Yes/No), NOT one field per option. */
const radioPeers = (el: Element): HTMLInputElement[] => {
  if ((el.getAttribute("type") || "").toLowerCase() !== "radio") return [];
  const name = el.getAttribute("name");
  if (!name) return [];
  return Array.from(
    el.ownerDocument.querySelectorAll('input[type="radio"][name="' + CSS.escape(name) + '"]'),
  ) as HTMLInputElement[];
};

/** One radio's own option label ("Yes"), independent of the group question. */
const radioOptionLabel = (el: Element): string =>
  (accName(el) || "").replace(/\s+/g, " ").replace(/\*/g, "").trim();

/** Group question for a radio/checkbox option ("Yes" alone is meaningless). */
const groupContext = (el: Element): string => {
  const type = (el.getAttribute("type") || "").toLowerCase();
  if (type !== "radio" && type !== "checkbox") return "";
  const name = el.getAttribute("name");
  if (!name) return "";
  const d = el.ownerDocument;
  const peers = d.querySelectorAll(
    'input[type="' + type + '"][name="' + CSS.escape(name) + '"]');
  if (peers.length < 2) return ""; // lone consent checkbox keeps its own label
  let scope: Element | null = el.parentElement;
  for (let dep = 0; scope && dep < 5 && scope.tagName !== "FORM" && scope.tagName !== "BODY";
       dep++, scope = scope.parentElement) {
    let foreign = false;
    for (const inp of Array.from(scope.querySelectorAll("input, select, textarea"))) {
      if (inp.getAttribute("name") !== name) { foreign = true; break; }
    }
    if (foreign) return "";
    for (const c of Array.from(scope.querySelectorAll("legend, .legend, label"))) {
      if (!c.querySelector("input") && !c.contains(el) && c.textContent?.trim())
        return c.textContent.replace(/\s+/g, " ").replace(/\*/g, "").trim();
    }
  }
  return "";
};

/** ARIA-role equivalent of radioPeers() for a custom-widget radio (Google
 *  Forms / MS Forms `div[role=radio]`, no shared `name`) — its `role=radio`
 *  siblings inside the closest `[role=radiogroup]` ancestor. Empty when not
 *  inside such a group (a lone/standalone role=radio keeps single-field
 *  behavior, same as a lone native radio). */
const ariaTogglePeers = (el: Element): Element[] => {
  if ((el.getAttribute("role") || "").toLowerCase() !== "radio") return [];
  const group = el.closest('[role="radiogroup"]');
  if (!group) return [];
  return Array.from(group.querySelectorAll('[role="radio"]'));
};

/** The ARIA radio group's own question text — the closest [role=radiogroup]
 *  ancestor's aria-labelledby, resolved via resolveLabelledBy. */
const ariaRadioGroupLabel = (el: Element): string => {
  const group = el.closest('[role="radiogroup"]');
  const lb = group?.getAttribute("aria-labelledby");
  if (!lb) return "";
  return resolveLabelledBy(lb, el.getRootNode() as Document | ShadowRoot)
    .replace(/\s+/g, " ").replace(/\*/g, "").trim();
};

/** One ARIA radio/checkbox option's own label ("Fluent"), independent of the
 *  group question — mirrors radioOptionLabel() for the native case. */
const ariaOptionLabel = (el: Element): string =>
  (accName(el) || "").replace(/\s+/g, " ").replace(/\*/g, "").trim();

/** ARIA fallback for groupContext() — a checkbox with no `name` (Google/MS
 *  Forms custom widget) finds its question via the closest
 *  [role=list][aria-labelledby] ancestor instead of a name-shared sibling
 *  scan. Only checkbox uses this: radio's ARIA group label is resolved
 *  separately by ariaRadioGroupLabel() (radio is deduped to one field and
 *  never reaches this per-option label path). */
const ariaGroupContext = (el: Element): string => {
  if ((el.getAttribute("role") || "").toLowerCase() !== "checkbox") return "";
  const list = el.closest('[role="list"][aria-labelledby]');
  const lb = list?.getAttribute("aria-labelledby");
  if (!lb) return "";
  return resolveLabelledBy(lb, el.getRootNode() as Document | ShadowRoot)
    .replace(/\s+/g, " ").replace(/\*/g, "").trim();
};

/** Nearest section context — a preceding heading or enclosing fieldset legend.
 *  Mirrors Field_.section (nearest heading / fieldset legend). */
const sectionFor = (el: Element): string => {
  const fs = el.closest("fieldset");
  const leg = fs?.querySelector("legend");
  if (leg?.textContent?.trim()) return leg.textContent.replace(/\s+/g, " ").trim();
  // Multi-button upload widgets (Greenhouse Resume/CV: Attach/Dropbox/Google
  // Drive/manual) label the wrapping [role=group] via aria-labelledby, not a
  // fieldset/legend — the file input's OWN explicit <label for> is decoy text
  // ("Attach") shared by its sibling buttons, not the field's real name.
  const group = el.closest("[role=group][aria-labelledby], [role=radiogroup][aria-labelledby]");
  const labelledBy = group?.getAttribute("aria-labelledby");
  if (labelledBy) {
    const doc = el.ownerDocument;
    const text = labelledBy.split(/\s+/).filter(Boolean)
      .map((id) => doc.getElementById(id)?.textContent?.trim())
      .filter(Boolean).join(" ");
    if (text) return text.replace(/\s+/g, " ").trim();
  }
  let node: Element | null = el;
  while (node) {
    let sib: Element | null = node.previousElementSibling;
    while (sib) {
      if (/^H[1-4]$/.test(sib.tagName) && sib.textContent?.trim())
        return sib.textContent.replace(/\s+/g, " ").trim();
      const h = sib.querySelector?.("h1, h2, h3, h4");
      if (h?.textContent?.trim()) return h.textContent.replace(/\s+/g, " ").trim();
      sib = sib.previousElementSibling;
    }
    node = node.parentElement;
  }
  return "";
};

// ── required detection (UPGRADE: aria + visual marker, not just el.required) ─
/** Many ATS mark a field required only VISUALLY — a `*`/`.req`/`.required`/
 *  `.asterisk` span in the label, with no `required`/`aria-required` on the
 *  control. Surface it so the agent treats the field as required and fills it
 *  instead of skipping. Ports observer.py::labelRequiredMarker. */
const labelRequiredMarker = (el: Element): boolean => {
  const d = el.ownerDocument;
  const ids = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
  let labs = ids.map((id) => d.getElementById(id)).filter(Boolean) as Element[];
  if (!labs.length && (el as HTMLElement).id) {
    const l = d.querySelector('label[for="' + CSS.escape((el as HTMLElement).id) + '"]');
    if (l) labs = [l];
  }
  if (!labs.length) { const w = el.closest("label"); if (w) labs = [w]; }
  for (const l of labs) {
    if (l.querySelector('[class*="req"], .required, .asterisk')) return true;
    if (/\*\s*$/.test((l.textContent || "").trim())) return true;
  }
  return false;
};

const requiredFor = (el: Element): boolean =>
  (el as HTMLInputElement).required ||
  el.hasAttribute("required") ||
  el.getAttribute("aria-required") === "true" ||
  shadowHostAttr(el, "required") !== null ||
  shadowHostAttr(el, "aria-required") === "true" ||
  labelRequiredMarker(el);

// ── visible validation error via aria-describedby ───────────────────────────
/** A shown described span (aria-describedby) — surfaced as an error so a re-fill
 *  after a failed submit sees what the site rejected. Latent/hidden help spans
 *  are ignored (an error only counts once visible). Ports observer.py error path. */
const describedError = (el: Element): string | null => {
  const d = el.ownerDocument;
  const ids = (el.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
  for (const id of ids) {
    const e = d.getElementById(id);
    if (e && e.textContent?.trim() && isVisible(e))
      return e.textContent.replace(/\s+/g, " ").trim();
  }
  return null;
};

const ftype = (el: Element): string => {
  const tag = el.tagName.toLowerCase();
  const role = (el.getAttribute("role") || "").toLowerCase();
  const type = (el.getAttribute("type") || "").toLowerCase();
  const hasPopup = (el.getAttribute("aria-haspopup") || "").toLowerCase();
  if (tag === "textarea") return "textarea";
  if (tag === "select" || role === "combobox" || role === "listbox" || hasPopup === "listbox") return "select";
  if (type === "file") return "file";
  if (type === "checkbox" || role === "checkbox") return "checkbox";
  if (type === "radio" || role === "radio") return "radio";
  if (tag === "button" || type === "submit" || type === "button" || role === "button" || tag === "a") return "button";
  return "text";
};

// ── option harvesting (kept) ────────────────────────────────────────────────
const _collectOpts = (els: Element[]): string[] =>
  els
    .filter((o) => isVisible(o))
    .map((o) => (o.textContent || "").trim())
    .filter((v) => !_isPlaceholder(v));

// Some ATSes keep a combobox's option list ONLY in an embedded form-schema JSON
// (window.__remixContext / __NEXT_DATA__), never the DOM. Serialize that (per
// frame) and recover a field's choices by its id/name. Mirrors schemaOptions.
const _pageJsonCache = new WeakMap<Window, string>();
const _pageJson = (win: Window): string => {
  const cached = _pageJsonCache.get(win);
  if (cached !== undefined) return cached;
  const parts: string[] = [];
  const w = win as unknown as Record<string, unknown>;
  for (const v of [w.__remixContext, w.__NEXT_DATA__]) {
    if (v) { try { parts.push(JSON.stringify(v)); } catch {} }
  }
  try { parts.push(Array.from(win.document.scripts).map((s) => s.textContent || "").join("\n")); } catch {}
  const joined = parts.join("\n");
  _pageJsonCache.set(win, joined);
  return joined;
};
const schemaOptions = (el: Element): string[] => {
  let keys: string[] = [];
  if ((el as HTMLElement).id) keys.push((el as HTMLElement).id);
  const nm = el.getAttribute("name");
  if (nm) keys.push(nm);
  const lb = el.getAttribute("aria-labelledby");
  if (lb) for (const part of lb.split(/\s+/)) keys.push(part.replace(/-label$/, ""));
  keys = keys.flatMap((k) => {
    const m = k.match(/^react-select-(.+?)-(input|live-region|placeholder)$/);
    return m ? [m[1], k] : [k];
  });
  const json = _pageJson(ownerWin(el));
  for (const key of keys) {
    const at = json.indexOf('"name":"' + key + '"');
    if (at < 0) continue;
    const vi = json.indexOf('"values":', at);
    const oi = json.indexOf('"options":', at);
    let s = vi;
    if (oi >= 0 && (vi < 0 || oi < vi)) s = oi;
    if (s < 0) continue;
    const lb2 = json.indexOf("[", s);
    const rb = json.indexOf("]", lb2);
    if (lb2 < 0 || rb < 0) continue;
    const slice = json.slice(lb2, rb + 1);
    const out: string[] = [];
    const re = /"label":"((?:[^"\\]|\\.)*)"/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(slice))) {
      try { out.push(JSON.parse('"' + m[1] + '"')); } catch { out.push(m[1]); }
    }
    if (out.length) return out;
  }
  return [];
};

const extractOptions = (el: Element): string[] => {
  const d = el.ownerDocument;
  // 0. Radio group — the peers' own labels ARE the legal choices ("Yes"/"No").
  const peers = radioPeers(el);
  if (peers.length > 1) return peers.map(radioOptionLabel).filter(Boolean);
  // 1. Native <select> — always in the DOM.
  if (el.tagName === "SELECT") {
    return Array.from((el as HTMLSelectElement).options)
      .map((o) => o.value || (o.textContent || "").trim())
      .filter((v) => !_isPlaceholder(v));
  }
  // Steps 2-7 harvest options via DOM proximity / document-wide search — a
  // currently-open dropdown ANYWHERE on the page (step 6) or even a listbox
  // sharing an ancestor (steps 4-5) would otherwise get attributed to a plain
  // text field just because it happened to be snapshotted in the same
  // observe() pass. Only a field that IS itself dropdown-like (matches
  // ftype()'s own "select" definition, or explicitly owns a popup via
  // aria-controls/aria-owns) may go looking for options at all.
  const role = el.getAttribute("role") || "";
  const hasPopup = (el.getAttribute("aria-haspopup") || "").toLowerCase();
  const ownsPopup = !!(el.getAttribute("aria-controls") || el.getAttribute("aria-owns"));
  const looksLikeDropdown = role === "listbox" || role === "combobox" || hasPopup === "listbox" || ownsPopup;
  if (!looksLikeDropdown) return [];
  // 2. Custom A11y dropdown — options may be inside the element.
  if (role === "listbox" || role === "combobox") {
    const inside = _collectOpts(Array.from(el.querySelectorAll('[role="option"]')));
    if (inside.length) return inside;
  }
  // 3. Linked via aria-controls.
  const controls = el.getAttribute("aria-controls");
  if (controls) {
    const listbox = d.getElementById(controls);
    if (listbox) {
      const opts = _collectOpts(Array.from(listbox.querySelectorAll('[role="option"]')));
      if (opts.length) return opts;
    }
  }
  // 4. Sibling listbox.
  const parent = el.parentElement;
  if (parent) {
    const sib = _collectOpts(Array.from(parent.querySelectorAll('[role="option"]')));
    if (sib.length) return sib;
  }
  // 5. Grandparent wrapper.
  const grandparent = parent?.parentElement;
  if (grandparent) {
    const sib = _collectOpts(Array.from(grandparent.querySelectorAll('[role="option"]')));
    if (sib.length) return sib;
  }
  // 6. Document-wide visible options (portals / overlays) — legal ONLY while
  // THIS control's own menu is open (aria-expanded). A closed combobox must
  // never inherit whatever unrelated menu happens to be mounted at snapshot
  // time (dial-code / EEO lists bleeding onto every select on Greenhouse).
  if ((el.getAttribute("aria-expanded") || "").toLowerCase() === "true") {
    const all = _collectOpts(Array.from(d.querySelectorAll('[role="option"]')));
    if (all.length) return all;
  }
  // 7. Embedded form-schema JSON (lazy combobox, options never in DOM).
  return schemaOptions(el);
};

const _sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Resolve as soon as check() returns truthy — driven by MutationObserver
 *  (NOT throttled in hidden tabs), with a setTimeout only as the failure
 *  timeout (in a hidden tab it clamps to ≥1s — that only slows the MISS
 *  case, the hit resolves instantly on the DOM mutation). `extraTarget` is
 *  a shadow root the trigger's portal menu lives inside — a document-level
 *  MutationObserver does not cross a shadow boundary. */
export const waitForDom = <T>(
  check: () => T | null,
  timeoutMs: number,
  extraTarget?: Node,
): Promise<T | null> => {
  const first = check();
  if (first) return Promise.resolve(first);
  return new Promise((resolve) => {
    let done = false;
    const mos: MutationObserver[] = [];
    const finish = (v: T | null) => {
      if (done) return;
      done = true;
      mos.forEach((m) => m.disconnect());
      clearTimeout(timer);
      resolve(v);
    };
    const onMut = () => {
      const v = check();
      if (v) finish(v);
    };
    const targets: Node[] = [document.documentElement];
    if (extraTarget && extraTarget !== document.documentElement) targets.push(extraTarget);
    for (const t of targets) {
      const m = new MutationObserver(onMut);
      m.observe(t, { childList: true, subtree: true, attributes: true });
      mos.push(m);
    }
    const timer = setTimeout(() => finish(check()), timeoutMs);
  });
};

// ── force-open latency caps ─────────────────────────────────────────────────
// The force-open pass is SERIAL (only one menu can be open at a time) and runs
// on every prepare, so its per-field cost multiplies by the page's blind-select
// count. Poll fast with a short per-field cap, and stop force-opening entirely
// once the page-level budget is spent — a select we couldn't harvest degrades
// to an optionless field (same as a failed force-open today), it doesn't hang
// the whole prepare.
const FORCE_OPEN_TIMEOUT_MS = 350; // first attempt's mutation-wait timeout
const FORCE_OPEN_RETRY_TIMEOUT_MS = 400; // after the fallback re-click
const COMBOBOX_PICK_TIMEOUT_MS = 700;
const FORCE_OPEN_SETTLE_MS = 80; // post-Escape settle (was 200ms)
const FORCE_OPEN_PAGE_BUDGET_MS = 4000;

// Options harvested by a force-open, cached for the page's lifetime keyed by
// selector+label. A growth re-prepare re-snapshots EVERY field; without the
// cache it re-clicks every dropdown (seconds of serial polling + visible menu
// flashing) to re-learn options that never change within a page visit.
const _optionsCache = new Map<string, string[]>();
const _optionsCacheKey = (el: SnapshotEl): string => el.selector + " " + el.label;

/** Test-only reset: the cache is module-level (page-lifetime), so vitest cases
 *  reusing the same jsdom document/selectors must clear it between tests. */
export const clearSnapshotOptionCache = (): void => {
  _optionsCache.clear();
};

/** Fire a full pointer→mouse→click sequence at an element's center. A bare
 *  `.click()` is NOT enough for libraries like react-select, which commit a
 *  selection on `mousedown` (and ignore a lone synthetic click). */
const _realClick = (el: HTMLElement) => {
  const r = el.getBoundingClientRect();
  const view = el.ownerDocument.defaultView ?? window;
  const init: MouseEventInit = {
    bubbles: true, cancelable: true, view,
    clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
  };
  el.dispatchEvent(new PointerEvent("pointerdown", init));
  el.dispatchEvent(new MouseEvent("mousedown", init));
  el.dispatchEvent(new PointerEvent("pointerup", init));
  el.dispatchEvent(new MouseEvent("mouseup", init));
  el.dispatchEvent(new MouseEvent("click", init));
};

/** Candidate option nodes for THIS combobox only — scope to the listbox it owns
 *  via aria-controls/aria-owns; fall back to the whole frame only when unlinked. */
const _optionScope = (el: HTMLElement): ParentNode => {
  const id = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
  if (id) {
    const esc = CSS.escape(id);
    for (const r of collectRoots()) {
      const lb = r.querySelector("#" + esc);
      if (lb) return lb;
    }
  }
  // Unlinked: the element's own root (shadow root for a web-component control;
  // the document otherwise — light-DOM portals/overlays still reachable there).
  return el.getRootNode() as Document | ShadowRoot;
};

/** Try to open a custom dropdown and return the newly-visible options. */
const _forceOpenOptions = async (trigger: HTMLElement): Promise<string[]> => {
  // Options already visible BEFORE the click belong to some other control's
  // still-open menu (a portal Escape failed to close) — never attribute them
  // to this trigger. A scope linked via aria-controls/aria-owns is trusted
  // wholesale; the unlinked whole-root fallback keeps only fresh nodes.
  const root = trigger.getRootNode() as Document | ShadowRoot;
  const stale = new Set(
    Array.from(root.querySelectorAll('[role="option"]')).filter((o) => isVisible(o)),
  );
  const check = (): string[] | null => {
    const scope = _optionScope(trigger);
    const linked = (scope as Node).nodeType === Node.ELEMENT_NODE;
    let els = Array.from(scope.querySelectorAll('[role="option"]'));
    if (!linked) els = els.filter((o) => !stale.has(o));
    const opts = _collectOpts(els);
    return opts.length ? opts : null;
  };
  // A shadow root's own MutationObserver.observe(subtree) does not see
  // mutations inside a DIFFERENT shadow root, and a document-level observer
  // cannot cross a shadow boundary at all — pass the trigger's own root as
  // extraTarget so a web-component ATS's portal menu is still observed.
  const shadowTarget = root instanceof ShadowRoot ? root : undefined;
  // preventScroll: a plain focus() scrolls the focused element into view —
  // on a tall page every force-open yanked the user to the field's position.
  trigger.focus({ preventScroll: true });
  _realClick(trigger);
  const first = await waitForDom(check, FORCE_OPEN_TIMEOUT_MS, shadowTarget);
  if (first) return first;
  const control = trigger.closest('[class*="control"], [role="combobox"]');
  if (control && control !== trigger) _realClick(control as HTMLElement);
  const second = await waitForDom(check, FORCE_OPEN_RETRY_TIMEOUT_MS, shadowTarget);
  return second ?? [];
};

/** Find an element by durable selector across the top frame and every
 *  same-origin child frame (a snapshotted field may live in an iframe). */
export const findEl = (selector: string): HTMLElement | null => {
  for (const r of collectRoots()) {
    const el = r.querySelector(selector) as HTMLElement | null;
    if (el) return el;
  }
  return null;
};

// ── PageObserver — read the live form into facts ────────────────────────────
const SNAPSHOT_SELECTOR =
  "input, textarea, select, button, a[href], [role=combobox], [role=listbox], [role=checkbox], [role=radio], [role=button], [role=textbox]";

/** A [role=listbox] that some other control owns via aria-controls/aria-owns
 *  is that combobox's popup MENU, not a standalone field — snapshotting it
 *  yields a phantom "select" whose label is the concatenated option texts. */
const isOwnedPopup = (el: Element, root: ParentNode): boolean => {
  if ((el.getAttribute("role") || "").toLowerCase() !== "listbox") return false;
  const id = (el as HTMLElement).id;
  if (!id) return false;
  return !!root.querySelector('[aria-controls~="' + id + '"], [aria-owns~="' + id + '"]');
};

export class PageObserver {
  private root: Document;

  constructor(root: Document = document) {
    this.root = root;
  }

  /** Core snapshot (synchronous) — walks the top frame + same-origin iframes. */
  observe(): SnapshotEl[] {
    const out: SnapshotEl[] = [];
    let i = 0;
    // A radio group (shared `name`) is ONE logical question with mutually
    // exclusive options — snapshot it as ONE field (first radio seen is the
    // group's representative), never one field per option. Two independent
    // fields would let the LLM answer each option separately (both "checked"),
    // and would anchor two overlapping on-page badges over one question.
    const seenRadioGroups = new Set<string>();
    // ARIA-role radio groups (Google/MS Forms custom widgets, no `name`) get
    // the same one-field-per-question dedup, keyed on the group CONTAINER
    // element instead of a name string.
    const seenAriaRadioGroups = new Set<Element>();
    for (const r of collectRoots(this.root)) {
      for (const el of Array.from(r.querySelectorAll(SNAPSHOT_SELECTOR))) {
        const type = (el.getAttribute("type") || "").toLowerCase();
        if (el.tagName === "INPUT" && ["hidden", "reset", "image"].includes(type)) continue;
        if (isOwnedPopup(el, r)) continue;
        if (type === "radio") {
          const peers = radioPeers(el);
          if (peers.length > 1) {
            const name = el.getAttribute("name")!;
            if (seenRadioGroups.has(name)) continue;
            seenRadioGroups.add(name);
          }
        } else if ((el.getAttribute("role") || "").toLowerCase() === "radio") {
          const aPeers = ariaTogglePeers(el);
          if (aPeers.length > 1) {
            const group = el.closest('[role="radiogroup"]')!;
            if (seenAriaRadioGroups.has(group)) continue;
            seenAriaRadioGroups.add(group);
          }
        }
        // A file input is often display:none behind a styled drag-drop zone;
        // surface it (so the agent can attach a resume) UNLESS an ancestor is
        // hidden (a future wizard step that must not leak in).
        const surfaced = isFileInput(el) && !hiddenAncestor(el);
        if (!isVisible(el) && !surfaced) continue;
        out.push(this.build(el, "e" + i++));
      }
    }
    return out;
  }

  /** Async snapshot that clicks each select/combobox to force lazy-rendered
   *  options into the DOM, captures them, then closes the dropdown. The version
   *  the content script should use. */
  async observeWithOptions(): Promise<SnapshotEl[]> {
    const observeT0 = performance.now();
    const base = this.observe();
    perfMark("observe:sync_walk", performance.now() - observeT0);
    this.pressEscape();
    if (!document.hidden) await _sleep(FORCE_OPEN_SETTLE_MS);

    const deadline = Date.now() + FORCE_OPEN_PAGE_BUDGET_MS;
    let cacheHits = 0;
    let forceOpened = 0;
    let budgetSkipped = 0;
    for (const el of base) {
      if (el.field_type !== "select") continue;
      if (el.options.length > 0) continue; // already found statically

      // Cached from an earlier force-open on this page — options don't change
      // within a page visit; reuse instead of re-clicking every dropdown on a
      // growth re-prepare (serial polling + visible menu flashing).
      const cached = _optionsCache.get(_optionsCacheKey(el));
      if (cached?.length) { el.options = cached; cacheHits++; continue; }

      const trigger = findEl(el.selector);
      if (!trigger) continue;

      // A hidden <select> sibling holds the real options on some ATS — read it
      // directly (prefer textContent: hidden selects store codes, UI shows labels).
      const parent = trigger.parentElement;
      const hiddenSelect = parent?.querySelector("select:not([data-otc-ref])") as HTMLSelectElement | null;
      if (hiddenSelect) {
        const opts = Array.from(hiddenSelect.options)
          .map((o) => (o.textContent || "").trim() || o.value)
          .filter((v) => !_isPlaceholder(v));
        if (opts.length) { el.options = opts; continue; }
      }

      // Budget spent — leave the remaining blind selects optionless (the same
      // degraded state a failed force-open yields) rather than stall the prepare.
      if (Date.now() > deadline) { budgetSkipped++; continue; }

      const forceT0 = performance.now();
      const opts = await _forceOpenOptions(trigger);
      perfMark("observe:force_open_select", performance.now() - forceT0, { field: el.label });
      forceOpened++;
      if (opts.length) {
        el.options = opts;
        _optionsCache.set(_optionsCacheKey(el), opts);
      }
      this.pressEscape();
      if (!document.hidden) await _sleep(FORCE_OPEN_SETTLE_MS);
    }
    perfMark("observe:force_open_total", performance.now() - observeT0, {
      forceOpened, cacheHits, budgetSkipped,
    });
    return base;
  }

  private pressEscape() {
    for (const d of collectDocuments(this.root))
      d.body?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  }

  private build(el: Element, ref: string): SnapshotEl {
    el.setAttribute("data-otc-ref", ref);
    const peers = radioPeers(el);
    const isRadioGroup = peers.length > 1;
    const ariaPeers = isRadioGroup ? [] : ariaTogglePeers(el);
    const isAriaRadioGroup = ariaPeers.length > 1;
    let label: string;
    if (isRadioGroup) {
      // The group's question, never one option's own label ("Yes") — the
      // options array (extractOptions) carries the per-option choices.
      label = groupContext(el) || (accName(el) || "").replace(/\s+/g, " ").replace(/\*/g, "").trim();
    } else if (isAriaRadioGroup) {
      // Same contract, ARIA-role path (Google/MS Forms — no shared `name`).
      label = ariaRadioGroupLabel(el) || ariaOptionLabel(el);
    } else {
      label = (accName(el) || "").replace(/\s+/g, " ").replace(/\*/g, "").trim();
      const group = groupContext(el) || ariaGroupContext(el);
      if (group && group !== label) label = group + " — " + label;
    }
    const c = el.getAttribute("maxlength");
    const section = sectionFor(el);
    // For a radio group, the "current value" is whichever peer is checked
    // (never just this representative radio's own checked state).
    const checkedPeer = isRadioGroup
      ? peers.find((p) => p.checked)
      : isAriaRadioGroup
        ? ariaPeers.find((p) => p.getAttribute("aria-checked") === "true")
        : undefined;
    const raw = isRadioGroup
      ? (checkedPeer ? radioOptionLabel(checkedPeer) : "")
      : isAriaRadioGroup
        ? (checkedPeer ? ariaOptionLabel(checkedPeer) : "")
        : (el as HTMLInputElement).value;
    // A durable #id / nth-of-type path is unreachable across a shadow boundary
    // (document.querySelector won't pierce it); for a shadow-encapsulated field
    // address it by the ref we just tagged — findEl resolves it via collectRoots.
    // An ARIA radio group's representative div has no id/name either — same
    // ref-based addressing, resolved back to the live peer set at fill time
    // via ariaTogglePeers (mirrors the native path's name-based re-derivation).
    const selector = el.getRootNode() instanceof ShadowRoot
      ? '[data-otc-ref="' + ref + '"]'
      : isRadioGroup
        ? 'input[type="radio"][name="' + CSS.escape(el.getAttribute("name")!) + '"]'
        : isAriaRadioGroup
          ? '[data-otc-ref="' + ref + '"]'
          : durable(el);
    return {
      ref,
      label: label.slice(0, 200),
      field_type: ftype(el),
      selector,
      options: isAriaRadioGroup ? ariaPeers.map(ariaOptionLabel).filter(Boolean) : extractOptions(el),
      required: requiredFor(el),
      autocomplete: el.getAttribute("autocomplete"),
      placeholder: el.getAttribute("placeholder"),
      name: el.getAttribute("name"),
      value: raw != null && raw !== "" ? String(raw) : null,
      maxlength: c != null ? parseInt(c, 10) : null,
      pattern: el.getAttribute("pattern"),
      accept: el.getAttribute("accept"),
      error: describedError(el),
      section: section || null,
    };
  }
}

/** querySelectorAll that pierces open shadow roots and same-origin iframes —
 *  for callers (form detection) that count controls without a full snapshot.
 *  A plain document.querySelectorAll misses every field on a web-component ATS. */
export const deepQueryAll = (selector: string, root: Document = document): Element[] => {
  const out: Element[] = [];
  for (const r of collectRoots(root)) out.push(...Array.from(r.querySelectorAll(selector)));
  return out;
};

/** Back-compat free functions (thin wrappers over PageObserver). */
export const snapshot = (): SnapshotEl[] => new PageObserver().observe();
export const snapshotWithOptions = (): Promise<SnapshotEl[]> =>
  new PageObserver().observeWithOptions();

// ── FormFiller — type backend values into the live form. NEVER submits. ──────
export interface AppliedField {
  selector: string;
  field_type: string;
  value: string;
  filename?: string;
  source?: string; // "profile" | "ai" | "gap" — drives the on-page mark
  required?: boolean; // for the pre-submit warn (required gaps only)
}

// ── file prefetch cache ──────────────────────────────────────────────────────
// Signed-URL attachments (resume / cover-letter PDFs) are downloaded while the
// user reviews the preview (background sends PREFETCH_FILES per frame), so the
// apply typing loop attaches from memory instead of blocking on a network
// fetch mid-fill. Keyed by URL — a resume switch mints a new signed URL, which
// naturally misses the cache. Page-lifetime; a failed prefetch evicts itself
// so apply falls back to a fresh fetch.
const _fileCache = new Map<string, Promise<Blob>>();

// Ask the background worker to fetch a file the page context couldn't (CORS).
// Returns null outside an extension context (jsdom tests, benchmark harness)
// or when the background declines (origin not allowlisted, network error).
const fetchFileViaBackground = async (url: string): Promise<Blob | null> => {
  try {
    if (typeof browser === "undefined" || !browser.runtime?.sendMessage) return null;
    const resp = (await browser.runtime.sendMessage({ type: "FETCH_FILE", url })) as {
      ok?: boolean;
      b64?: string;
      contentType?: string;
    } | null;
    if (!resp?.ok || typeof resp.b64 !== "string") return null;
    const bin = atob(resp.b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: resp.contentType || "application/pdf" });
  } catch {
    return null;
  }
};

export const prefetchFiles = (urls: string[]): void => {
  for (const url of urls) {
    if (!url || _fileCache.has(url)) continue;
    const p = fetch(url).then((r) => {
      if (!r.ok) throw new Error(`prefetch ${r.status}`);
      return r.blob();
    });
    p.catch(() => _fileCache.delete(url));
    _fileCache.set(url, p);
  }
};

export class FormFiller {
  /** Returns ONLY the fields actually applied to the live DOM. The panel renders
   *  its glass-box receipt from this — never the backend's intended `fields` — so
   *  a select we couldn't resolve is never reported as filled. */
  async apply(fields: AppliedField[]): Promise<AppliedField[]> {
    const applied: AppliedField[] = [];
    for (const f of fields) {
      if (!f.value) continue;
      const el = findEl(f.selector);
      if (!el) continue;
      const fieldT0 = performance.now();
      try {
        if (f.field_type === "file") {
          if (await this.attachFile(el as HTMLInputElement, f)) applied.push(f);
        } else if (f.field_type === "select") {
          if (await this.setSelect(el, f)) applied.push(f);
        } else if (f.field_type === "radio") {
          this.setRadioGroup(el, f.value);
          applied.push(f);
        } else if (f.field_type === "checkbox") {
          this.setToggle(el, f.value);
          applied.push(f);
        } else {
          this.setText(el, f.value);
          applied.push(f);
        }
      } catch (err) {
        // One broken field must not abort the rest of the fill.
        warn("applyFill error on", f.selector, err);
      }
      // Attribute a slow apply to its field: a missed combobox burns its full
      // poll budget, a cold file attach a network fetch — only outliers are
      // reported so a 20-field fill doesn't add 20 noise rows.
      const fieldMs = performance.now() - fieldT0;
      if (fieldMs > 250) {
        perfMark("apply:slow_field", fieldMs, { field: f.selector, type: f.field_type });
      }
    }
    return applied;
  }

  private async attachFile(input: HTMLInputElement, f: AppliedField): Promise<boolean> {
    const blob = await this.downloadAttachment(f.value);
    if (!blob) { warn("resume download failed", f.value); return false; }
    const filename = f.filename || (f.value.split("?")[0].split("/").pop() || "resume.pdf");
    const file = new File([blob], filename, { type: blob.type || "application/pdf" });
    const dt = new DataTransfer();
    dt.items.add(file);
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "files");
    if (descriptor && descriptor.set) descriptor.set.call(input, dt.files);
    else (input as any).files = dt.files;
    // Both events: native forms listen for `change`; React/Vue wrappers often
    // bind `input`. Firing one the site ignores is harmless.
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    // Verify the DOM actually holds the file — the receipt must never claim
    // an attach that the input silently rejected (e.g. accept-filtered).
    return (input.files?.length ?? 0) > 0;
  }

  /** Download an attachment: prefetch cache → page-context fetch → background
   *  proxy. The page context can be CORS-blocked for our storage origin; the
   *  background worker fetches CORS-free via host_permissions <all_urls>. */
  private async downloadAttachment(url: string): Promise<Blob | null> {
    const cached = _fileCache.get(url);
    if (cached) {
      const blob = await cached.catch(() => null); // failed prefetch → fetch fresh below
      if (blob) return blob;
    }
    try {
      const resp = await fetch(url);
      if (resp.ok) return await resp.blob();
      warn("attachment fetch not ok", resp.status, url);
    } catch (e) {
      warn("attachment fetch threw", e);
    }
    return fetchFileViaBackground(url);
  }

  private async setSelect(el: HTMLElement, f: AppliedField): Promise<boolean> {
    if (el.tagName !== "SELECT") {
      // Custom combobox — open it and click the matching [role=option], like a user.
      return this.pickComboboxOption(el, f.value);
    }
    const sel = el as HTMLSelectElement;
    const before = sel.selectedIndex;
    sel.value = f.value;
    if (sel.value !== f.value) {
      // Exact match failed (e.g. the LLM returned the visible option text
      // while the native <select> uses a different `value` attribute, or
      // stray whitespace/case drift) — fall back to a normalized match
      // against each option's own text AND value, same tolerance the
      // combobox path (pickComboboxOption) already applies.
      const norm = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();
      const want = norm(f.value);
      for (let i = 0; i < sel.options.length; i++) {
        const opt = sel.options[i];
        if (norm(opt.textContent || "") === want || norm(opt.value) === want) { sel.selectedIndex = i; break; }
      }
    }
    // A no-op (selectedIndex unchanged from before we touched it, and still
    // not matching the requested value) means nothing actually matched —
    // report failure instead of silently leaving the placeholder selected.
    if (sel.selectedIndex < 0 || (sel.selectedIndex === before && sel.value !== f.value)) {
      warn("select option not found:", f.value); return false;
    }
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  private setToggle(el: HTMLElement, value: string) {
    if (!(el instanceof HTMLInputElement)) { this.setAriaToggle(el, value); return; }
    const v = String(value).toLowerCase().trim();
    const truthy = !!v && !["0", "false", "no", "off", "", "null", "undefined"].includes(v);
    el.checked = truthy;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /** ARIA-role checkbox (Google/MS Forms `div[role=checkbox]`) — no
   *  `.checked` property; read current state via aria-checked, drive via a
   *  real pointer-event click (LL-005 — a bare attribute write wouldn't
   *  trigger the site's own React state), only clicking when the current
   *  state actually differs from the requested one. */
  private setAriaToggle(el: HTMLElement, value: string) {
    const v = value.trim().toLowerCase();
    const truthy = !!v && !["0", "false", "no", "off", "", "null", "undefined"].includes(v);
    const currently = el.getAttribute("aria-checked") === "true";
    if (truthy !== currently) _realClick(el);
  }

  /** `el` is the group's representative radio (the selector is name-based, so
   *  a plain querySelector only ever resolves to one peer) — find the peer
   *  whose OWN option label/value matches the backend's chosen answer and
   *  check exactly that one. Native radio-group exclusivity un-checks the rest. */
  private setRadioGroup(el: HTMLElement, value: string) {
    if (!(el instanceof HTMLInputElement)) { this.setAriaRadioGroup(el, value); return; }
    const peers = radioPeers(el);
    if (peers.length <= 1) { this.setToggle(el, value); return; }
    const target = value.trim().toLowerCase();
    const match =
      peers.find((p) => radioOptionLabel(p).toLowerCase() === target) ??
      peers.find((p) => p.value.toLowerCase() === target);
    if (!match) { warn("radio option not found:", value); return; }
    match.checked = true;
    match.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /** ARIA-role radio group (Google/MS Forms `div[role=radio]`) — re-derive
   *  the peer set structurally via ariaTogglePeers (mirrors setRadioGroup's
   *  native peer re-derivation via radioPeers) and click the matching
   *  option; native radio's mutual exclusivity has no ARIA equivalent, so
   *  only the target option is clicked (the site's own widget is
   *  responsible for un-checking its siblings on select, same as a real
   *  user click would trigger). */
  private setAriaRadioGroup(el: HTMLElement, value: string) {
    const peers = ariaTogglePeers(el);
    const group = peers.length > 1 ? (peers as HTMLElement[]) : [el];
    const target = value.trim().toLowerCase();
    const match = group.find((p) => ariaOptionLabel(p).toLowerCase() === target);
    if (!match) { warn("aria radio option not found:", value); return; }
    if (match.getAttribute("aria-checked") !== "true") _realClick(match);
  }

  private setText(el: HTMLElement, value: string) {
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    setter ? setter.call(el, value) : ((el as HTMLInputElement).value = value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /** Drive a custom combobox: open it, wait for its OWN listbox's
   *  [role=option] nodes to appear (event-driven — see waitForDom), fire a
   *  real pointer sequence on the one whose text matches (exact, then
   *  substring). Returns true only when an option was clicked. */
  private async pickComboboxOption(el: HTMLElement, value: string): Promise<boolean> {
    const norm = (s: string | null) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
    const want = norm(value);
    const check = (): Element | null => {
      const scope = _optionScope(el);
      const opts = Array.from(scope.querySelectorAll('[role="option"]')).filter((o) => isVisible(o));
      return (
        opts.find((o) => norm(o.textContent) === want) ??
        opts.find((o) => norm(o.textContent).includes(want) || want.includes(norm(o.textContent))) ??
        null
      );
    };
    const root = el.getRootNode() as Document | ShadowRoot;
    const shadowTarget = root instanceof ShadowRoot ? root : undefined;
    el.focus({ preventScroll: true });
    _realClick(el);
    const target = await waitForDom(check, COMBOBOX_PICK_TIMEOUT_MS, shadowTarget);
    if (target) { _realClick(target as HTMLElement); return true; }
    warn("combobox option not found:", value);
    return false;
  }
}

/** Back-compat free function. */
export const applyFill = (fields: AppliedField[]): Promise<AppliedField[]> =>
  new FormFiller().apply(fields);
