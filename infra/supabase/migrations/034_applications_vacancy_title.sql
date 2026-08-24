-- ============================================================
-- 034_applications_vacancy_title.sql — store the vacancy name at apply time.
--   applications.vacancy_title: the human-readable vacancy name (e.g.
--   "Senior Python Developer") captured from hh's vacancy dict when the
--   worker records an application. Lets the UI render a title instead of a
--   raw vacancy_id. employer_name already exists (added in 023).
-- Run AFTER 033_recruiter_questions.sql
-- ============================================================

ALTER TABLE applications
  ADD COLUMN IF NOT EXISTS vacancy_title text;
