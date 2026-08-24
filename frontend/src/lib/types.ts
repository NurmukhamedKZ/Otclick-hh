export type Resume = {
  id: string;
  hh_resume_id: string;
  title: string | null;
  status: string | null;
  synced_at: string | null;
};

export type ResumesList = { items: Resume[] };

export type Filter = {
  id: string;
  resume_id: string | null;
  name: string | null;
  text: string | null;
  area: number | null;
  experience: string | null;
  work_format: string | null;
  employment_form: string | null;
  search_field: string | null;
  period: number | null;
  excluded_text: string | null;
  enabled: boolean;
  ai_filter_enabled: boolean;
  created_at: string | null;
};

export type FilterCreate = {
  resume_id?: string | null;
  name?: string | null;
  text?: string | null;
  area?: number | null;
  experience?: string | null;
  work_format?: string | null;
  employment_form?: string | null;
  search_field?: string | null;
  period?: number | null;
  excluded_text?: string | null;
  enabled?: boolean;
  ai_filter_enabled?: boolean;
};

export type VacancyPreviewItem = {
  id: string | null;
  name: string | null;
  employer: string | null;
  area: string | null;
  salary: Record<string, unknown> | null;
  url: string | null;
};

export type FilterPreview = {
  found: number;
  items: VacancyPreviewItem[];
};

export type BlacklistEntry = {
  id: string;
  employer_id: string;
  employer_name: string | null;
  reason: string | null;
  created_at: string | null;
};

export type BlacklistCreate = {
  employer_id: string;
  employer_name?: string | null;
  reason?: string | null;
};

export type WorkerStatus = {
  state: "starting" | "running" | "paused_captcha" | "paused_limit" | "paused_antibot" | "idle" | "stopped";
  agent_state: "running" | "stopped";
  today_count: number;
  daily_limit: number;
  queued: number;
  next_run_at: string | null;
  last_error: string | null;
  skipped_has_test: number;
  /** "manual" = бесплатный тир: одна пачка по кнопке, суммарный лимит. */
  mode: "manual" | "auto";
  limit_total: number | null;
  total_used: number;
};

export type WorkerStartResponse = {
  state: string;
  queued: number;
};

export type WorkerStopResponse = {
  stopped: boolean;
};

export type AgentStartResponse = {
  agent_state: string;
};

export type AgentStopResponse = {
  stopped: boolean;
};

export type FormAnswer = {
  task_id: number;
  question: string;
  type: "choice" | "text";
  options?: { id: string; text: string }[];
  answer_id?: string;
  answer: string;
};

export type Application = {
  id: string;
  user_id: string;
  resume_id: string | null;
  vacancy_id: string;
  vacancy_title: string | null;
  employer_id: string | null;
  employer_name: string | null;
  status: string;
  cover_letter: string | null;
  applied_at: string | null;
  error: string | null;
  created_at: string;
  form_answers: FormAnswer[] | null;
};

export type CaptchaRequest = {
  id: string;
  user_id: string;
  storage_path: string | null;
  captcha_url: string | null;
  solved: boolean;
  created_at: string;
  solved_at: string | null;
};

export type SubscribeResponse = {
  checkout_url: string;
};

export type PortalResponse = {
  portal_url: string;
};

export type PaymentEntry = {
  provider_payment_id: string;
  amount: number | null;
  status: string;
  created_at: string | null;
};

export type BillingStatus = {
  plan: string;
  plan_expires_at: string | null;
  next_charge_at: string | null;
  has_access: boolean;
  history: PaymentEntry[];
};

export type NotificationRow = {
  id: string;
  type: string;
  payload: Record<string, unknown> | null;
  read: boolean;
  created_at: string;
};

export type AnalyticsBreakdown = {
  filter_id?: string | null;
  resume_id?: string | null;
  with_letter?: boolean;
  name?: string;
  title?: string;
  sent: number;
  replied: number;
  invited: number;
  reply_rate: number | null;
  invite_rate: number | null;
};

export type RelevanceVerdict = {
  vacancy_id: string;
  vacancy_name: string | null;
  employer_name: string | null;
  relevant: boolean;
  reason: string | null;
  created_at: string | null;
};

export type Analytics = {
  days: number;
  /** true — RPC упал, все числа ниже нулевые и ничего не значат. */
  error?: boolean;
  funnel: {
    ai_checked: number;
    ai_kept: number;
    sent: number;
    viewed: number;
    replied: number;
    invited: number;
    discarded: number;
    waiting: number;
  };
  kpi: {
    view_rate: number | null;
    reply_rate: number | null;
    invite_rate: number | null;
    discard_rate: number | null;
    median_reaction_hours: number | null;
    stuck_forms: number;
    stuck_captcha: number;
    stuck_drafts: number;
  };
  ai_filter: { checked: number; kept: number; dropped: number; drop_rate: number | null };
  by_filter: AnalyticsBreakdown[];
  by_resume: AnalyticsBreakdown[];
  by_letter: AnalyticsBreakdown[];
  failures: { status: string; count: number }[];
  silent_employers: { employer_id: string; employer_name: string | null; sent: number }[];
  daily: { date: string; sent: number; invited: number }[];
};
