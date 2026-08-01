import type { FilledField } from "./api";

/** Q&A pairs worth remembering: a field we filled whose value the user then
 *  changed to something non-empty. Unchanged values teach the memory nothing,
 *  and a cleared field is a rejection, not an answer. */
export function collectEdits(
  applied: (FilledField & { label?: string })[],
  current: { ref: string; label: string; value: string }[],
): { question: string; answer: string }[] {
  const before = new Map(applied.map((f) => [f.ref, f]));
  const out: { question: string; answer: string }[] = [];
  for (const cur of current) {
    const prev = before.get(cur.ref);
    if (!prev) continue;
    const question = (cur.label ?? "").trim();
    const answer = (cur.value ?? "").trim();
    if (!question || !answer) continue;
    if (answer === (prev.value ?? "").trim()) continue;
    out.push({ question, answer });
  }
  return out;
}
