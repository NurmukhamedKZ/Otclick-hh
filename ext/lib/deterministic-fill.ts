import type { FilledField } from "./api";

// Facts we can fill verbatim, no LLM round trip: label pattern → fact key.
// Order matters — the first match wins, so narrower patterns come first.
const RULES: { key: string; re: RegExp }[] = [
  { key: "email", re: /e-?mail|почт|электрон/i },
  { key: "phone", re: /phone|телефон|моб/i },
  { key: "city", re: /город|city|населённый пункт/i },
  { key: "citizenship", re: /гражданств|citizenship/i },
  { key: "full_name", re: /ф\.?и\.?о|имя и фамилия|фамилия и имя|full name|your name/i },
  { key: "last_name", re: /фамилия|last name|surname/i },
  { key: "first_name", re: /имя|first name/i },
  { key: "title", re: /должность|позици|position|desired role/i },
];

export function deterministicFields(
  els: {
    ref: string;
    selector: string;
    field_type: string;
    label?: string;
    required?: boolean;
  }[],
  facts: Record<string, string>,
  resume?: { url: string; filename: string },
): FilledField[] {
  const out: FilledField[] = [];
  for (const el of els) {
    if (el.field_type === "file") {
      if (resume) {
        out.push({
          frame_id: 0,
          ref: el.ref,
          selector: el.selector,
          field_type: "file",
          value: resume.url,
          filename: resume.filename,
          source: "profile",
          required: Boolean(el.required),
        });
      }
      continue;
    }
    // textarea = an open question; only the LLM can answer those.
    if (el.field_type !== "text") continue;
    const label = el.label ?? "";
    const rule = RULES.find((r) => r.re.test(label));
    const value = rule ? facts[rule.key] : undefined;
    if (!value) continue;
    out.push({
      frame_id: 0,
      ref: el.ref,
      selector: el.selector,
      field_type: "text",
      value,
      source: "profile",
      required: Boolean(el.required),
    });
  }
  return out;
}
