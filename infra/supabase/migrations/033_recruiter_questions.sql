-- ============================================================
-- 033_recruiter_questions.sql — question-asking escalation.
-- The recruiter agent, when it can't confidently answer on its own, now asks
-- the candidate 1-3 short questions instead of writing a guessed draft reply.
-- The user answers on the Todo page ("Вопросы" tab); the worker poller picks
-- the answered set up and re-invokes the agent with the answers fed back in.
-- Statuses: 'pending' (awaiting the user) -> 'answered' (poller's work queue)
--   -> 'completed' (agent resumed) | 'discarded' (user dismissed).
-- ============================================================

CREATE TABLE IF NOT EXISTS recruiter_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES profiles(id) ON DELETE CASCADE,
  negotiation_id text NOT NULL,
  chat_id text,
  applicant_id text,
  message_id text,
  questions jsonb NOT NULL,
  answers jsonb,
  reason text,
  question_text text,
  vacancy_id text,
  vacancy_title text,
  employer_name text,
  status text NOT NULL DEFAULT 'pending',
  created_at timestamptz DEFAULT now(),
  answered_at timestamptz,
  resolved_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_recruiter_questions_user_status
  ON recruiter_questions (user_id, status);

ALTER TABLE recruiter_questions ENABLE ROW LEVEL SECURITY;  -- service_role only, no policies