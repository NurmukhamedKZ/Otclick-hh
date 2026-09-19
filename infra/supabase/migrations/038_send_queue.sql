-- ============================================================
-- 037_send_queue.sql — exact-text approval + persistent send queue.
-- Queue rows are durable and are NOT consumed by any worker yet. Real HH submit
-- remains additionally gated by ALLOW_REAL_APPLY=false in backend config.
-- ============================================================

CREATE TABLE IF NOT EXISTS application_send_queue (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  vacancy_pipeline_id uuid NOT NULL REFERENCES vacancy_pipeline(id) ON DELETE CASCADE,
  resume_id uuid REFERENCES resumes(id) ON DELETE SET NULL,
  hh_vacancy_id text NOT NULL,
  approved_letter_hash text NOT NULL,
  approved_letter_text text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (
    status IN ('queued', 'sending', 'sent', 'failed', 'manual_required', 'cancelled')
  ),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_error text,
  queued_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (vacancy_pipeline_id),
  CHECK (char_length(approved_letter_hash) = 64),
  CHECK (char_length(approved_letter_text) > 0)
);

CREATE INDEX IF NOT EXISTS idx_application_send_queue_user_status
  ON application_send_queue (user_id, status, queued_at);

ALTER TABLE application_send_queue ENABLE ROW LEVEL SECURITY;
