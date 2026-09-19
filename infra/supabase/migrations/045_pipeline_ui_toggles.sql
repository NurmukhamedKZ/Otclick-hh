-- ============================================================
-- 045_pipeline_ui_toggles.sql — every runtime switch lives in the UI.
-- The funnel runs next to the legacy auto-apply loop, so discovery needs its
-- own flag: worker_enabled must keep meaning "auto-apply loop".
-- real_apply_enabled is the per-user half of the send gate; the ALLOW_REAL_APPLY
-- env flag stays as the outer kill switch and both must be on to submit to hh.
-- ============================================================

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS discovery_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS real_apply_enabled boolean NOT NULL DEFAULT false;
