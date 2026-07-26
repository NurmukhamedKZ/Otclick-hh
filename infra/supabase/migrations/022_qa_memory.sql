-- ============================================================
-- 022_qa_memory.sql — user-curated Q&A memory.
-- Only answers the USER edited (when approving a form draft) land here,
-- plus manual entries from the account page. Injected into every AI prompt
-- that needs facts about the candidate (form tests, recruiter chat).
-- Run AFTER 021_filters_resume_set_null.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS qa_memory (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES profiles(id) ON DELETE CASCADE,
  question text NOT NULL,
  answer text NOT NULL,
  source text NOT NULL DEFAULT 'form',        -- 'form'|'manual'
  vacancy_id text,                            -- where it came from, informational
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  UNIQUE (user_id, question)
);

CREATE INDEX IF NOT EXISTS idx_qa_memory_user ON qa_memory (user_id);

ALTER TABLE qa_memory ENABLE ROW LEVEL SECURITY;  -- service_role only
