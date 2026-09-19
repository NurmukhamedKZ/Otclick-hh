-- ============================================================
-- 036_cover_letter_meta.sql — provenance for persistent funnel drafts.
-- A generated draft must remain traceable to the confirmed facts/profile/model
-- used to produce it. Approval/send are intentionally not introduced here.
-- ============================================================

ALTER TABLE vacancy_pipeline
  ADD COLUMN IF NOT EXISTS cover_letter_meta jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE vacancy_pipeline
  DROP CONSTRAINT IF EXISTS vacancy_pipeline_cover_letter_meta_object;

ALTER TABLE vacancy_pipeline
  ADD CONSTRAINT vacancy_pipeline_cover_letter_meta_object
  CHECK (jsonb_typeof(cover_letter_meta) = 'object');
