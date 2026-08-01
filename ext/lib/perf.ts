import { browser } from "wxt/browser";
// ── Perf instrumentation ─────────────────────────────────────────────────────
// Lightweight timing so a real prepare/apply run can be attributed to a stage
// (DOM force-open, snapshot, network/LLM round trip, typing) instead of
// guessing. Every context (content script per frame, background) buffers its
// own spans in a module-level array; the background is the only context that
// sees a whole run end-to-end (it fans out to every frame and calls the
// backend), so it drains its own buffer, merges in each frame's drained spans
// (sent back over the SNAPSHOT/APPLY response), and calls `perfReport` once
// per run. That logs a console.table AND persists the last PERF_LOG_MAX runs
// to browser.storage.local under `otc_perf_log` — inspect a run without
// reopening devtools mid-flow: `browser.storage.local.get("otc_perf_log")`.

export type PerfSpan = { label: string; ms: number; meta?: Record<string, unknown> };

let buf: PerfSpan[] = [];

/** A run-scoped span collector for the background, where prepare/apply runs
 *  OVERLAP (a growth re-prepare racing the first prepare, a second apply click
 *  while typing). The shared module buffer misattributes spans under that
 *  concurrency — one report showed two net:commit rows from two interleaved
 *  applies. Each background run owns a PerfRun; the module-level buffer stays
 *  for content-script frames (their spans travel back over sendResponse and
 *  are pushed into the owning run). */
export class PerfRun {
  private spans: PerfSpan[] = [];
  private readonly t0 = performance.now();

  async time<T>(label: string, fn: () => Promise<T>, meta?: Record<string, unknown>): Promise<T> {
    const s0 = performance.now();
    try {
      return await fn();
    } finally {
      this.spans.push(
        meta ? { label, ms: performance.now() - s0, meta } : { label, ms: performance.now() - s0 },
      );
    }
  }

  mark(label: string, ms: number, meta?: Record<string, unknown>): void {
    this.spans.push(meta ? { label, ms, meta } : { label, ms });
  }

  push(spans: PerfSpan[]): void {
    this.spans.push(...spans);
  }

  report(runId: string, kind: string): void {
    void perfReport(runId, kind, this.spans, performance.now() - this.t0);
  }
}

/** Time an async operation and buffer the result. */
export const perfTime = async <T>(
  label: string,
  fn: () => Promise<T>,
  meta?: Record<string, unknown>,
): Promise<T> => {
  const t0 = performance.now();
  try {
    return await fn();
  } finally {
    buf.push(meta ? { label, ms: performance.now() - t0, meta } : { label, ms: performance.now() - t0 });
  }
};

/** Record an already-measured duration (e.g. a per-field force-open cost). */
export const perfMark = (label: string, ms: number, meta?: Record<string, unknown>): void => {
  buf.push(meta ? { label, ms, meta } : { label, ms });
};

/** Merge spans measured in another context (a content-script frame reporting
 *  back to the background over sendResponse) into this context's buffer. */
export const perfPush = (spans: PerfSpan[]): void => {
  buf.push(...spans);
};

/** Pull and clear this context's buffered spans. */
export const perfDrain = (): PerfSpan[] => {
  const out = buf;
  buf = [];
  return out;
};

const PERF_LOG_KEY = "otc_perf_log";
const PERF_LOG_MAX = 20;

/** Log + persist one completed run. Call once, from the background — the only
 *  context that sees the full cross-frame + network trace for a run.
 *
 *  `wallMs` is the run's REAL elapsed time (caller measures start→report).
 *  Never sum the spans for a total: net:fill/net:analyze run in PARALLEL and
 *  snapshot spans NEST (roundtrip ⊇ observeWithOptions ⊇ force_open_total ⊇
 *  per-select), so a sum double/quadruple-counts — early reports showed
 *  "14.4s total" for a 7.4s run this way. The span sum is still logged
 *  separately as `spanSum` to make the overlap visible. */
export const perfReport = async (
  runId: string,
  kind: string,
  spans: PerfSpan[],
  wallMs?: number,
): Promise<void> => {
  const spanSum = spans.reduce((s, x) => s + x.ms, 0);
  const wall = wallMs ?? spanSum;
  try {
    const rows = [...spans]
      .sort((a, b) => b.ms - a.ms)
      .map((s) => ({ label: s.label, ms: Math.round(s.ms), ...(s.meta ?? {}) }));
    console.groupCollapsed(
      `[otc-perf] ${kind} ${runId} — ${Math.round(wall)}ms wall (spans overlap/nest; sum ${Math.round(spanSum)}ms)`,
    );
    console.table(rows);
    console.groupEnd();
  } catch {
    // console.table unavailable in some contexts (tests) — persistence below still runs.
  }
  try {
    const { [PERF_LOG_KEY]: log } = (await browser.storage.local.get(PERF_LOG_KEY)) as Record<string, unknown[] | undefined>;
    const next = [
      ...(log ?? []),
      { id: runId, kind, total: Math.round(wall), spanSum: Math.round(spanSum), spans, ts: Date.now() },
    ].slice(-PERF_LOG_MAX);
    await browser.storage.local.set({ [PERF_LOG_KEY]: next });
  } catch {
    // browser.storage unavailable (tests) — the console.table above already ran.
  }
};

/** Read back persisted runs for offline analysis (devtools console or a debug UI). */
export const perfGetLog = async (): Promise<
  { id: string; kind: string; total: number; spans: PerfSpan[]; ts: number }[]
> => {
  // wxt/browser types storage reads as {}, unlike chrome's any.
  const { [PERF_LOG_KEY]: log } = (await browser.storage.local.get(PERF_LOG_KEY)) as Record<
    string,
    { id: string; kind: string; total: number; spans: PerfSpan[]; ts: number }[] | undefined
  >;
  return log ?? [];
};
