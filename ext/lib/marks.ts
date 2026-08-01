// On-page fill-confidence marks. An extension-owned overlay layer (NOT injected
// into the site's DOM tree — the page's React reconciler would wipe it) anchors
// a badge to each filled field via getBoundingClientRect.
//
// A gap field ("NEEDS YOU") carries NO inline input — the user fills the real
// field on the page as normal; we OBSERVE their typing and report each answer
// via the onGapAnswer callback, so the sidebar can list what it will remember
// and save on demand. NEVER submits: this only reads rects + field values and
// fires a callback.

import { findEl } from "./snapshot";

export type MarkSource = "profile" | "ai" | "gap";
export interface MarkField {
  selector: string;
  source: MarkSource;
  label: string;
  field_type?: string;
  required?: boolean;
}

// One captured gap answer the user typed into a NEEDS-YOU field.
export interface GapAnswer {
  selector: string;
  question: string;
  value: string;
  required?: boolean;
}

const LAYER_ID = "otc-marks-layer";
const LABELS: Record<MarkSource, string> = {
  profile: "PROFILE",
  ai: "AI · REVIEW",
  gap: "NEEDS YOU",
};
const COLORS: Record<MarkSource, string> = {
  profile: "#059669",
  ai: "#6D5AE6",
  gap: "#B45309",
};

export function countUnresolvedRequiredGaps(fields: MarkField[]): number {
  return fields.filter((f) => f.source === "gap" && f.required).length;
}

let anchors: { el: HTMLElement; wrap: HTMLElement; selector: string }[] = [];
let gapCleanups: (() => void)[] = [];
let listenersBound = false;
let repoObserver: MutationObserver | null = null;
let repoTimer: ReturnType<typeof setTimeout> | null = null;
const WATCH_MAX_MS = 5 * 60 * 1000;

function scheduleReposition(): void {
  if (repoTimer) return;
  repoTimer = setTimeout(() => {
    repoTimer = null;
    reposition();
  }, 150);
}

function ensureLayer(): HTMLElement {
  let layer = document.getElementById(LAYER_ID);
  if (!layer) {
    layer = document.createElement("div");
    layer.id = LAYER_ID;
    // Absolute (document-coordinate) layer, NOT fixed: absolutely-positioned
    // marks live in the page's scroll flow, so they scroll WITH the fields
    // natively — no per-scroll JS repositioning (that lags a frame behind the
    // native scroll and makes the badges visibly "fly" over the form).
    layer.style.cssText =
      "position:absolute;top:0;left:0;pointer-events:none;z-index:2147483646;";
    document.body.appendChild(layer);
  }
  if (!listenersBound) {
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition, true);
    listenersBound = true;
  }
  // Scroll/resize alone miss a form that REFLOWS in place — an async-loaded
  // section pushing fields down, a validation error expanding a field's height,
  // an accordion. A debounced childList/subtree observer re-anchors the badges
  // to their fields' new rects. childList-only (no attributes) so our own
  // style writes on the overlay don't loop; self-caps after a few minutes.
  if (!repoObserver) {
    repoObserver = new MutationObserver(scheduleReposition);
    repoObserver.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(() => {
      repoObserver?.disconnect();
      repoObserver = null;
    }, WATCH_MAX_MS);
  }
  return layer;
}

// Half the badge height — the badge is raised by this so its vertical centre
// sits on the field's TOP border (a corner tab), clearing the value text below.
const BADGE_HALF = 11;
// Extra push so the corner tab sits further right/lower than dead-center on
// the border — clears the question label (right side) and the answer value
// (below the top border) instead of overlapping either.
const BADGE_RIGHT_EXTRA = 50;
const BADGE_DOWN_EXTRA = 8;

function reposition(): void {
  const sx = window.scrollX;
  const sy = window.scrollY;
  for (const { el, wrap } of anchors) {
    const r = el.getBoundingClientRect();
    // Document coordinates (viewport rect + scroll offset) so the mark stays
    // pinned to its field as the page scrolls, with no per-frame JS lag.
    wrap.style.top = `${r.top + sy - BADGE_HALF + BADGE_DOWN_EXTRA}px`;
    wrap.style.left = `${r.left + sx + BADGE_RIGHT_EXTRA}px`;
    wrap.style.width = `${Math.max(0, r.width - BADGE_RIGHT_EXTRA)}px`;
  }
}

export function clearMarks(): void {
  document.getElementById(LAYER_ID)?.remove();
  for (const off of gapCleanups) off();
  gapCleanups = [];
  anchors = [];
}

// Hide (or restore) a gap field's amber badge the moment the user's typed
// value resolves (or clears) it — the badge must track the field's live
// state, not just its state at APPLY time.
export function setMarkResolved(selector: string, resolved: boolean): void {
  const a = anchors.find((x) => x.selector === selector);
  if (a) a.wrap.style.display = resolved ? "none" : "";
}

// Scroll a filled field into view and shake it left-right — the sidebar
// review row's "show me" affordance. Prefers the live anchor (already
// resolved at render time); falls back to a fresh findEl for a field the mark
// layer never anchored (e.g. a skipped/empty row). Returns false when the
// field can't be located in THIS frame's DOM (the caller then knows to route
// elsewhere — a field can live in a different frame than the sidebar).
export function scrollAndFlash(el: HTMLElement): void {
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  flashField(el);
}

export function jumpToField(selector: string): boolean {
  const el = anchors.find((x) => x.selector === selector)?.el ?? findEl(selector);
  if (!el) return false;
  scrollAndFlash(fieldRowContainer(el));
  return true;
}

// ATS forms wrap one label+control pair in a row container (Greenhouse
// ".field-wrapper", generic ".form-field"/".form-group", etc.) — shaking the
// bare <input> only moves the box, leaving its label dead still, which reads
// as the wrong element moving. Climb to that row so label + control shake as
// one unit. Stops at the first ancestor matching a known row class; a form
// with none of these conventions falls back to the element itself rather
// than risk grabbing an ancestor that spans multiple unrelated fields.
const ROW_SELECTORS =
  '.field-wrapper, .form-field, .form-group, .field-row, .form-row, [class*="field-wrapper" i], [class*="fieldWrapper" i]';
function fieldRowContainer(el: HTMLElement): HTMLElement {
  const row = el.closest(ROW_SELECTORS);
  return row instanceof HTMLElement ? row : el;
}

// Shake the field itself (left-right wobble, decaying) instead of drawing any
// overlay — draws the eye without adding a color/shape the page didn't have.
function flashField(el: HTMLElement): void {
  const prevTransform = el.style.transform;
  const restore = () => { el.style.transform = prevTransform; };
  // jsdom (unit tests) has no Web Animations API — no-op there, nothing to clean up.
  if (typeof el.animate === "function") {
    el.animate(
      [
        { transform: "translateX(0)" },
        { transform: "translateX(-8px)" },
        { transform: "translateX(7px)" },
        { transform: "translateX(-5px)" },
        { transform: "translateX(4px)" },
        { transform: "translateX(-2px)" },
        { transform: "translateX(0)" },
      ],
      { duration: 750, easing: "ease-out" },
    ).onfinish = restore;
  }
}

function makeBadge(source: MarkSource): HTMLElement {
  const badge = document.createElement("div");
  badge.style.cssText =
    `display:inline-block;pointer-events:auto;font:600 10px/1.4 ui-monospace,monospace;` +
    `color:#fff;background:${COLORS[source]};padding:2px 7px;border-radius:99px;` +
    `box-shadow:0 1px 4px rgba(0,0,0,.25);white-space:nowrap;`;
  badge.textContent = LABELS[source];
  return badge;
}

// A radio field's selector is name-based (one logical question, mutually
// exclusive options) — querySelector only ever resolves the FIRST peer, so
// reading/watching that one element misses a user selecting a LATER option.
function radioGroupPeers(el: HTMLInputElement): HTMLInputElement[] {
  const name = el.getAttribute("name");
  if (!name) return [el];
  return Array.from(
    el.ownerDocument.querySelectorAll('input[type="radio"][name="' + CSS.escape(name) + '"]'),
  ) as HTMLInputElement[];
}

// Find the ancestor that wraps BOTH the react-select filter input and its
// sibling `.select__single-value`/`.select__placeholder` display node. The
// nearest class*="select" ancestor (e.g. `.select__input-container`) is often
// too narrow — the display node lives one level up as a SIBLING, not a
// descendant, of that inner wrapper — so walk up until a wider ancestor's
// subtree actually contains the display node.
function selectContainer(el: HTMLElement): Element | null {
  let node: Element | null = el.parentElement;
  for (let i = 0; i < 8 && node; i++) {
    if (node.querySelector('[class*="single-value"], [class*="placeholder"]')) return node;
    node = node.parentElement;
  }
  return el.closest('[class*="select"]');
}

// The user's current value for a field, across native + custom controls.
function readFieldValue(el: HTMLElement): string {
  const tag = el.tagName;
  // react-select (and similar) custom comboboxes: the filter <input role="combobox">
  // this selector resolves to is a search box, not the value holder — its native
  // `.value` is cleared right after a selection commits. The picked option's text
  // renders in a sibling `.select__single-value` node inside the same control.
  // Checked BEFORE the generic INPUT branch below, which would otherwise always
  // win first and return the (always-empty) native `.value`, so observeEdit
  // would never see a filled/edited select reach pendingAnswers.
  if (tag === "INPUT" && el.getAttribute("role") === "combobox") {
    const singleValue = selectContainer(el)?.querySelector('[class*="single-value"]');
    if (singleValue) return (singleValue.textContent || "").trim();
    return (el as HTMLInputElement).value ?? "";
  }
  if (tag === "INPUT") {
    const input = el as HTMLInputElement;
    const t = (input.type || "").toLowerCase();
    if (t === "radio") {
      const checked = radioGroupPeers(input).find((p) => p.checked);
      return checked ? (checked.value || "on") : "";
    }
    if (t === "checkbox") return input.checked ? (input.value || "on") : "";
    return input.value ?? "";
  }
  if (tag === "TEXTAREA") return (el as HTMLTextAreaElement).value ?? "";
  if (tag === "SELECT") {
    const s = el as HTMLSelectElement;
    return (s.selectedOptions[0]?.textContent || s.value || "").trim();
  }
  return (el.textContent || "").trim();
}

// Watch a field for the user's own input and report each change that differs
// from the field's baseline value (captured at attach time — "" for a gap
// field left empty, the filled value for a profile/ai field). Returns a
// cleanup that detaches the listeners.
function observeEdit(
  el: HTMLElement,
  f: MarkField,
  baseline: string,
  onEdit: (a: GapAnswer) => void,
): () => void {
  const handler = () => {
    const value = readFieldValue(el).trim();
    if (value === baseline) return;
    onEdit({ selector: f.selector, question: f.label, value, required: f.required });
  };
  // A radio group's `change` event fires only on the newly-checked peer, never
  // on the anchor (first) radio when the user picks a LATER option — listen on
  // every peer so any choice in the group is observed.
  const targets: HTMLElement[] =
    el instanceof HTMLInputElement && el.type === "radio" ? radioGroupPeers(el) : [el];
  for (const t of targets) {
    t.addEventListener("input", handler);
    t.addEventListener("change", handler);
  }
  // react-select commits an option pick as a React state update (mousedown on
  // the listbox item), not a native input/change event on the filter <input> —
  // so the listeners above never fire for these controls. Watch the control's
  // DOM for the resulting text swap in `.select__single-value` instead.
  let comboObserver: MutationObserver | null = null;
  if (el instanceof HTMLInputElement && el.getAttribute("role") === "combobox") {
    const container = selectContainer(el);
    if (container) {
      comboObserver = new MutationObserver(handler);
      comboObserver.observe(container, { childList: true, subtree: true, characterData: true });
    }
  }
  return () => {
    for (const t of targets) {
      t.removeEventListener("input", handler);
      t.removeEventListener("change", handler);
    }
    comboObserver?.disconnect();
  };
}

export function renderMarks(
  fields: MarkField[],
  onGapAnswer?: (a: GapAnswer) => void,
): void {
  clearMarks();
  const layer = ensureLayer();
  for (const f of fields) {
    const el = findEl(f.selector);
    if (!el) continue;
    const wrap = document.createElement("div");
    wrap.style.cssText = "position:absolute;pointer-events:none;text-align:right;";
    wrap.appendChild(makeBadge(f.source));
    layer.appendChild(wrap);
    anchors.push({ el, wrap, selector: f.selector });
    if (onGapAnswer) {
      const baseline = readFieldValue(el).trim();
      gapCleanups.push(observeEdit(el, f, baseline, onGapAnswer));
    }
  }
  reposition();
}
