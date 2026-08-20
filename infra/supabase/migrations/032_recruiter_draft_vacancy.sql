-- ============================================================
-- 032_recruiter_draft_vacancy.sql — persist vacancy title/employer on
-- recruiter_drafts/recruiter_todos at creation time, like form_drafts
-- already does. Without this the Todo page had to join against the last
-- 50 hh negotiations to show a vacancy name, which missed almost every
-- draft whose chat wasn't among the most recently updated ones.
-- ============================================================

ALTER TABLE recruiter_drafts
  ADD COLUMN IF NOT EXISTS vacancy_id text,
  ADD COLUMN IF NOT EXISTS vacancy_title text,
  ADD COLUMN IF NOT EXISTS employer_name text;

ALTER TABLE recruiter_todos
  ADD COLUMN IF NOT EXISTS vacancy_id text,
  ADD COLUMN IF NOT EXISTS vacancy_title text,
  ADD COLUMN IF NOT EXISTS employer_name text;
