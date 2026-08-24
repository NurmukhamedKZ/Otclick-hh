import type { NotificationRow } from "@/lib/types";

/**
 * Human-readable summary of a notification payload.
 *
 * The backend (backend/app/services/notifications.py) emits ~14 distinct
 * `type` values, each with its own payload shape — see the per-type branches
 * below. Returns undefined when there's nothing useful to show, so callers
 * can omit the subtitle line entirely (matching the old `JSON.stringify`
 * fallback only as a last resort for unknown types).
 */
export function formatNotificationBody(n: NotificationRow): string | undefined {
  const p = n.payload;
  if (!p) return undefined;

  // Coerce a payload value to string, tolerating null/undefined/numbers.
  const s = (v: unknown): string | undefined =>
    v === null || v === undefined ? undefined : String(v);

  switch (n.type) {
    case "captcha":
      if (p.resolved === true) return "капча решена — продолжаю";
      if (p.vacancy_id) return `вакансия ${p.vacancy_id}`;
      return undefined;

    case "limit_reached": {
      const sleep = s(p.sleep_s);
      const mins = sleep ? Math.round(Number(sleep) / 60) : undefined;
      const src = s(p.source) === "hh" ? "hh.ru" : "дневной лимит";
      return mins ? `пауза ~${mins} мин (${src})` : src;
    }

    case "limit_total": {
      const lim = s(p.limit);
      return lim ? `бесплатный лимит исчерпан (${lim})` : "бесплатный лимит исчерпан";
    }

    case "antibot_pause": {
      const count = s(p.count);
      const win = s(p.window);
      const pause = s(p.pause_s);
      const mins = pause ? Math.round(Number(pause) / 60) : undefined;
      const head = count && win ? `${count}/${win} блоков` : "антибот-блок";
      return mins ? `${head} · пауза ~${mins} мин` : head;
    }

    case "worker_stop": {
      const reason = s(p.reason);
      if (reason === "token_dead") return "токен hh истёк";
      if (reason === "account_banned") return "аккаунт заблокирован";
      return reason ? `причина: ${reason}` : undefined;
    }

    case "token_dead":
      return p.vacancy_id ? `вакансия ${p.vacancy_id}` : "токен hh истёк";

    case "account_banned":
      return p.vacancy_id ? `вакансия ${p.vacancy_id}` : "аккаунт заблокирован";

    case "resume_missing": {
      // Two shapes: {resume_id, vacancy_id} | {disabled_filters, reason}
      if (p.disabled_filters !== undefined) {
        const n = s(p.disabled_filters);
        return n ? `отключено фильтров: ${n}` : "резюме удалено на hh";
      }
      if (p.vacancy_id) return `вакансия ${p.vacancy_id}`;
      return undefined;
    }

    case "recruiter_draft":
    case "recruiter_question":
      // payload is {negotiation_id} — the ID alone isn't user-meaningful,
      // so leave the subtitle empty; the title already says what happened.
      return undefined;

    case "recruiter_todo":
      return s(p.title) ?? undefined;

    case "form_approval":
    case "cover_letter_written": {
      const parts: string[] = [];
      const employer = s(p.employer);
      const title = s(p.vacancy_title);
      if (employer) parts.push(employer);
      if (title) parts.push(title);
      if (p.vacancy_id) parts.push(`#${p.vacancy_id}`);
      return parts.length ? parts.join(" · ") : undefined;
    }

    case "web_session_expired":
      return s(p.reason) ?? "переподключите аккаунт hh";

    default:
      // Unknown type — never dump raw JSON to the UI. Surface nothing rather
      // than leak internal keys.
      return undefined;
  }
}
