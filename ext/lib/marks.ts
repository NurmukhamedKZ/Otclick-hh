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
// exported: the qa_memory edit diff reads the same field kinds (input,
// textarea, select, contenteditable) after the user reviews the form.
export function readFieldValue(el: HTMLElement): string {
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
